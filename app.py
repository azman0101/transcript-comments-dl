"""
Streamlit Web App to Fetch YouTube Transcript and Comments
=========================================================

This Streamlit application provides a simple user interface for retrieving the
transcript (subtitles) and top‑level comments from a YouTube video.  It uses
``yt‑dlp`` under the hood to download the comments and subtitles for a given
video URL.  The resulting transcript and comments are displayed directly in
the browser and can optionally be downloaded as plain text files.

Requirements
------------

To run this application you must have the following tools installed on your
machine:

* **Python 3.8 or newer**
* **yt‑dlp** – a fork of youtube‑dl capable of downloading comments and
  subtitles.  Installation instructions are available in the official
  repository: https://github.com/yt‑dlp/yt‑dlp
* **Streamlit** – used for the web interface.
* **NumPy** – required for audio processing and signal generation. Install via `pip install numpy`.

Once all dependencies are installed you can launch the app with:

```
streamlit run app.py
```

After starting, open the provided local URL in your browser and paste a YouTube
link to retrieve its transcript and comments.

Please note that fetching comments for popular videos can take a few minutes
depending on the number of comments available.
"""

import base64
import io
import json
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import streamlit as st


def generate_notification_sound() -> bytes:
    """Generate a clean notification beep sound using a simple tone.
    
    Creates a pleasant notification sound with proper ADSR envelope
    to avoid clicks and artifacts.
    
    Returns
    -------
    bytes
        WAV audio data for a short notification beep.
    """
    sample_rate = 44100  # Hz
    duration = 0.4  # seconds - slightly longer for smoother sound
    frequency = 800  # Hz (notification tone)
    
    # Generate time array
    t = np.linspace(0, duration, int(sample_rate * duration))
    
    # Generate pure sine wave
    audio_data = np.sin(2 * np.pi * frequency * t)
    
    # Create ADSR envelope for clean, professional sound
    # Attack: 0.02s, Decay: 0.05s, Sustain: 0.20s, Release: 0.13s
    attack_samples = int(0.02 * sample_rate)
    decay_samples = int(0.05 * sample_rate)
    sustain_samples = int(0.20 * sample_rate)
    release_samples = len(audio_data) - attack_samples - decay_samples - sustain_samples
    
    envelope = np.ones(len(audio_data))
    
    # Attack: linear ramp up
    envelope[:attack_samples] = np.linspace(0, 1, attack_samples)
    
    # Decay: exponential decay to sustain level (0.7)
    decay_curve = np.exp(np.linspace(0, -1.5, decay_samples))
    envelope[attack_samples:attack_samples + decay_samples] = 1 - (1 - 0.7) * (1 - decay_curve)
    
    # Sustain: constant level
    envelope[attack_samples + decay_samples:attack_samples + decay_samples + sustain_samples] = 0.7
    
    # Release: smooth exponential fade out
    release_curve = np.exp(np.linspace(0, -5, release_samples))
    envelope[-release_samples:] = 0.7 * release_curve
    
    # Apply envelope to audio
    audio_data = audio_data * envelope
    
    # Scale to 16-bit integer range with slight reduction to avoid clipping
    audio_data = (audio_data * 30000).astype(np.int16)
    
    # Create WAV file in memory
    byte_io = io.BytesIO()
    with wave.open(byte_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data.tobytes())
    
    return byte_io.getvalue()


def run_yt_dlp(args: List[str]) -> None:
    """Run a yt‑dlp command and raise an exception if it fails.

    The function is separated for easier mocking during tests.  It calls
    ``subprocess.run`` with the provided arguments and checks the return code.

    Parameters
    ----------
    args:
        A list of command line arguments to pass directly to ``yt‑dlp``.

    Raises
    ------
    RuntimeError
        If ``yt‑dlp`` returns a non‑zero exit status.
    """
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"yt‑dlp failed with status {result.returncode}:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def fetch_comments(video_url: str, work_dir: Path) -> List[Dict[str, str]]:
    """Download and parse YouTube comments using yt‑dlp.

    yt‑dlp can write comments into the JSON metadata file when invoked with
    ``--write-comments``.  We specify a custom output template so that the
    resulting ``.info.json`` file has a predictable name based on the video ID.

    Parameters
    ----------
    video_url:
        The full YouTube URL provided by the user.
    work_dir:
        A directory in which to store temporary files.  The JSON file will be
        created here.

    Returns
    -------
    List[Dict[str, str]]
        A list of dictionaries, where each dictionary contains the 'author'
        and 'text' of a comment.
    """
    # Derive a simple filename stem from the video URL by extracting the video
    # identifier.  This keeps file names short and avoids issues with special
    # characters in titles.
    video_id_match = re.search(r"(?<=v=)[^&?]+|(?<=youtu.be/)[^?&]+", video_url)
    if not video_id_match:
        raise ValueError("Impossible d'extraire l'identifiant de la vidéo.")
    video_id = video_id_match.group(0)
    json_path = work_dir / f"{video_id}.info.json"

    # Construct yt‑dlp command.  We always skip downloading the media.
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-info-json",
        "--write-comments",
        "-o",
        str(work_dir / f"{video_id}"),
        video_url,
    ]
    run_yt_dlp(cmd)

    if not json_path.exists():
        raise FileNotFoundError(
            f"Fichier JSON introuvable : {json_path}. Assurez-vous que yt‑dlp est correctement installé."
        )

    with json_path.open("r", encoding="utf-8") as f:
        info = json.load(f)

    comments_raw = info.get("comments") or []
    comments_list: List[Dict[str, str]] = []
    for comment in comments_raw:
        text = comment.get("text") or comment.get("txt") or ""
        author = comment.get("author") or "Unknown"
        if text:
            comments_list.append({"author": author.strip(), "text": text.strip()})

    return comments_list


def parse_srt_contents(contents: str) -> str:
    """Convert an SRT subtitle file into plain text.

    SRT files consist of numbered blocks with timestamps followed by one or
    more lines of subtitle text.  This function strips away the sequence
    numbers and timestamps and joins the remaining text lines into a single
    coherent transcript.

    Parameters
    ----------
    contents:
        Raw contents of an SRT file decoded as UTF‑8.

    Returns
    -------
    str
        The cleaned transcript.
    """
    lines = contents.splitlines()
    transcript_lines: List[str] = []
    for line in lines:
        # Skip blank lines, purely numeric counters and timestamp lines
        if not line.strip():
            continue
        if re.match(r"^\d+$", line.strip()):
            continue
        if "-->" in line:
            continue
        transcript_lines.append(line.strip())
    return "\n".join(transcript_lines)


def fetch_transcript(video_url: str, work_dir: Path, language: str = "fr") -> Tuple[str, str]:
    """Download and parse YouTube subtitles using yt‑dlp.

    yt‑dlp will attempt to download manually provided subtitles first and fall
    back to automatically generated subtitles when ``--write-auto-subs`` is
    specified.  We request subtitles in the desired language and fall back to
    English if none are available.  The resulting transcript is returned as a
    string.

    Parameters
    ----------
    video_url:
        The YouTube URL.
    work_dir:
        Temporary directory used to store the downloaded subtitle file.
    language:
        Two‑letter language code (e.g. "fr" for French or "en" for English).

    Returns
    -------
    Tuple[str, str]
        A pair ``(lang_code, transcript)`` where ``lang_code`` is the
        language of the transcript that was actually used and ``transcript``
        contains the plain text extracted from the subtitles.  If neither
        manual nor auto subtitles are available the transcript string will
        be empty.
    """
    video_id_match = re.search(r"(?<=v=)[^&?]+|(?<=youtu.be/)[^?&]+", video_url)
    if not video_id_match:
        raise ValueError("Impossible d'extraire l'identifiant de la vidéo.")
    video_id = video_id_match.group(0)

    base_output = work_dir / f"{video_id}"
    # Try to fetch subtitles in the specified language
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-sub",
        "--write-auto-subs",
        "--sub-format",
        "srt",
        "--sub-lang",
        language,
        "-o",
        str(base_output),
        video_url,
    ]
    run_yt_dlp(cmd)

    # Look for files like <video_id>.<lang>.srt
    possible_files = list(work_dir.glob(f"{video_id}.*.srt"))
    selected_lang = ""
    subtitle_path: Optional[Path] = None
    for file in possible_files:
        suffix_parts = file.name.split(".")
        if len(suffix_parts) >= 3:
            lang_code = suffix_parts[-2]  # filename format: <id>.<lang>.srt
            if lang_code == language:
                subtitle_path = file
                selected_lang = lang_code
                break
    # If not found, fall back to the first available language
    if subtitle_path is None and possible_files:
        subtitle_path = possible_files[0]
        parts = subtitle_path.name.split(".")
        selected_lang = parts[-2] if len(parts) >= 3 else language

    transcript = ""
    if subtitle_path and subtitle_path.exists():
        with subtitle_path.open("r", encoding="utf-8") as f:
            contents = f.read()
        transcript = parse_srt_contents(contents)

    return selected_lang, transcript


def main() -> None:
    """Main Streamlit application entry point."""
    st.set_page_config(
        page_title="Transcripteur YouTube", page_icon="🎬", layout="centered"
    )
    st.title("Récupération de transcript et commentaires YouTube")

    st.markdown(
        """
        Entrez un lien **YouTube** ci‑dessous pour obtenir sa transcription et
        ses commentaires.  Le traitement utilise l'outil `yt‑dlp` en interne.
        Veillez donc à ce que celui‑ci soit installé sur votre machine.
        """
    )

    with st.form("input_form"):
        url = st.text_input(
            "Lien de la vidéo YouTube", placeholder="https://www.youtube.com/watch?v=..."
        )
        lang = st.selectbox(
            "Langue des sous‑titres",
            options=["fr", "en", "es", "de", "it"],
            index=0,
            help="Choisissez la langue à privilégier pour les sous‑titres."
        )
        download_transcript = st.checkbox(
            "Télécharger la transcription",
            value=True,
            help="Inclure la transcription dans le résultat."
        )
        download_comments = st.checkbox(
            "Télécharger les commentaires",
            value=True,
            help="Inclure les commentaires dans le résultat."
        )
        submitted = st.form_submit_button("Récupérer")

    if submitted:
        if not url:
            st.error("Merci de fournir une URL valide.")
            return
        if not download_transcript and not download_comments:
            st.error(
                "Veuillez sélectionner au moins une option de téléchargement."
            )
            return
        try:
            with tempfile.TemporaryDirectory() as tmpdir_str:
                tmpdir = Path(tmpdir_str)

                if download_comments:
                    with st.spinner("Téléchargement des commentaires..."):
                        comments = fetch_comments(url, tmpdir)
                else:
                    comments = []

                if download_transcript:
                    with st.spinner("Téléchargement de la transcription..."):
                        actual_lang, transcript = fetch_transcript(
                            url, tmpdir, lang
                        )
                else:
                    transcript = ""
                    actual_lang = ""

                st.success("Récupération terminée !")
                
                # Play notification sound using HTML audio with autoplay
                # This ensures the sound plays on every submission
                notification_sound = generate_notification_sound()
                audio_base64 = base64.b64encode(notification_sound).decode()
                audio_html = f"""
                    <audio autoplay>
                        <source src="data:audio/wav;base64,{audio_base64}" type="audio/wav">
                    </audio>
                """
                st.markdown(audio_html, unsafe_allow_html=True)

                # Display transcript
                if download_transcript:
                    if transcript:
                        st.subheader(f"Transcription ({actual_lang})")
                        st.download_button(
                            label="Télécharger la transcription",
                            data=transcript,
                            file_name=f"{actual_lang}_transcript.txt",
                            mime="text/plain",
                        )
                        st.text_area(
                            "Texte du transcript",
                            value=transcript,
                            height=300,
                        )
                    else:
                        st.warning("Aucune transcription n'a été trouvée pour cette vidéo.")

                # Display comments
                if download_comments:
                    if comments:
                        st.subheader(f"Commentaires ({len(comments)})")
                        # Prepare comments for download
                        comments_text = "\n\n".join(
                            [
                                f"Auteur : {c['author']}\n{c['text']}"
                                for c in comments
                            ]
                        )
                        st.download_button(
                            label="Télécharger les commentaires",
                            data=comments_text,
                            file_name="comments.txt",
                            mime="text/plain",
                        )
                        # Show a sample of the first 100 comments to avoid overloading
                        max_display = 100
                        for idx, comment in enumerate(comments[:max_display], start=1):
                            st.markdown(
                                f"**Commentaire {idx} (de {comment['author']}) :**\n"
                                f"> {comment['text']}"
                            )
                        if len(comments) > max_display:
                            st.info(
                                f"{len(comments) - max_display} autres commentaires non affichés."
                            )
                    else:
                        st.warning("Aucun commentaire n'a pu être récupéré pour cette vidéo.")
        except Exception as exc:
            st.error(f"Une erreur est survenue : {exc}")

    # Display footer with version
    try:
        with open("version.txt", "r") as f:
            version = f.read().strip()
    except FileNotFoundError:
        version = "development"
    st.markdown(f"<div style='text-align: center; color: grey;'>Version: {version}</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()