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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import streamlit as st


@dataclass
class VideoData:
    """A container for storing metadata about a single video."""

    url: str
    title: str
    transcript: str
    comments: List[Dict[str, str]]
    actual_lang: str = ""


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


def fetch_video_data(
    video_url: str,
    work_dir: Path,
    language: str,
    download_transcript: bool,
    download_comments: bool,
) -> VideoData:
    """Download all necessary video data using a single yt‑dlp invocation.

    This function fetches the video title, transcript, and comments in a
    single call to ``yt‑dlp`` to improve efficiency by avoiding multiple
    invocations.

    Parameters
    ----------
    video_url:
        The full YouTube URL provided by the user.
    work_dir:
        A temporary directory to store downloaded files.
    language:
        The preferred language for the transcript.
    download_transcript:
        A boolean indicating whether to download the transcript.
    download_comments:
        A boolean indicating whether to download the comments.

    Returns
    -------
    VideoData
        A dataclass containing the title, transcript, and comments.
    """
    video_id_match = re.search(r"(?<=v=)[^&?]+|(?<=youtu.be/)[^?&]+", video_url)
    if not video_id_match:
        raise ValueError("Impossible d'extraire l'identifiant de la vidéo.")
    video_id = video_id_match.group(0)
    json_path = work_dir / f"{video_id}.info.json"

    cmd = ["yt-dlp", "--skip-download", "-o", str(work_dir / f"{video_id}")]
    if download_transcript:
        cmd.extend(
            [
                "--write-sub",
                "--write-auto-subs",
                "--sub-format",
                "srt",
                "--sub-lang",
                language,
            ]
        )
    if download_comments:
        cmd.append("--write-comments")

    # If we need comments or a transcript (for the title), get the info json.
    if download_transcript or download_comments:
        cmd.append("--write-info-json")

    cmd.append(video_url)
    run_yt_dlp(cmd)

    # Extract transcript
    transcript = ""
    actual_lang = ""
    if download_transcript:
        possible_files = list(work_dir.glob(f"{video_id}.*.srt"))
        subtitle_path = next(iter(possible_files), None)
        if subtitle_path and subtitle_path.exists():
            with subtitle_path.open("r", encoding="utf-8") as f:
                transcript = parse_srt_contents(f.read())
            # Extract language from filename, e.g., "video_id.fr.srt"
            parts = subtitle_path.name.split(".")
            if len(parts) > 2:
                actual_lang = parts[-2]

    # Extract comments and title
    comments_list: List[Dict[str, str]] = []
    title = ""
    if download_transcript or download_comments:
        if not json_path.exists():
            raise FileNotFoundError(
                f"Fichier JSON introuvable : {json_path}. Assurez-vous que yt‑dlp est correctement installé."
            )
        with json_path.open("r", encoding="utf-8") as f:
            info = json.load(f)
        title = info.get("title", "Titre inconnu")
        if download_comments:
            comments_raw = info.get("comments", [])
            for comment in comments_raw:
                text = comment.get("text") or comment.get("txt", "")
                author = comment.get("author", "Auteur inconnu")
                if text:
                    comments_list.append(
                        {"author": author.strip(), "text": text.strip()}
                    )

    return VideoData(
        url=video_url,
        title=title,
        transcript=transcript,
        comments=comments_list,
        actual_lang=actual_lang,
    )


def main() -> None:
    """Main Streamlit application entry point."""
    st.set_page_config(
        page_title="Transcripteur YouTube", page_icon="🎬", layout="centered"
    )

    if "videos" not in st.session_state:
        st.session_state["videos"] = [
            {"url": "", "download_transcript": True, "download_comments": True}
        ]

    st.title("Récupération de transcript et commentaires YouTube")

    st.markdown(
        """
        Entrez un lien **YouTube** ci‑dessous pour obtenir sa transcription et
        ses commentaires.  Le traitement utilise l'outil `yt‑dlp` en interne.
        Veillez donc à ce que celui‑ci soit installé sur votre machine.
        """
    )

    lang = st.selectbox(
        "Langue des sous‑titres",
        options=["fr", "en", "es", "de", "it"],
        index=0,
        help="Choisissez la langue à privilégier pour les sous‑titres.",
    )

    for i, video in enumerate(st.session_state["videos"]):
        st.markdown("---")
        cols = st.columns([0.8, 0.2])
        video["url"] = cols[0].text_input(
            f"Lien de la vidéo YouTube #{i + 1}",
            value=video["url"],
            key=f"url_{i}",
        )
        if cols[1].button("🗑️", key=f"delete_{i}"):
            st.session_state["videos"].pop(i)
            st.experimental_rerun()

        cols = st.columns(2)
        video["download_transcript"] = cols[0].checkbox(
            "Télécharger la transcription",
            value=video["download_transcript"],
            key=f"transcript_{i}",
        )
        video["download_comments"] = cols[1].checkbox(
            "Télécharger les commentaires",
            value=video["download_comments"],
            key=f"comments_{i}",
        )

    st.button("Ajouter une autre vidéo", on_click=lambda: st.session_state["videos"].append(
        {"url": "", "download_transcript": True, "download_comments": True}
    ))

    submitted = st.button("Récupérer")

    if submitted:
        # Filter out empty URLs
        videos_to_process = [
            v for v in st.session_state["videos"] if v["url"].strip()
        ]
        if not videos_to_process:
            st.error("Merci de fournir au moins une URL valide.")
            return

        # Check that at least one download option is selected for each video
        for video in videos_to_process:
            if not video["download_transcript"] and not video["download_comments"]:
                st.error(
                    f"Pour la vidéo {video['url']}, veuillez sélectionner au moins une option de téléchargement."
                )
                return
        try:
            all_video_data = []
            with tempfile.TemporaryDirectory() as tmpdir_str:
                tmpdir = Path(tmpdir_str)
                for i, video in enumerate(videos_to_process, 1):
                    with st.spinner(
                        f"Traitement de la vidéo {i}/{len(videos_to_process)}..."
                    ):
                        video_data = fetch_video_data(
                            video["url"],
                            tmpdir,
                            lang,
                            video["download_transcript"],
                            video["download_comments"],
                        )
                        all_video_data.append(video_data)

            st.success("Récupération terminée !")

            notification_sound = generate_notification_sound()
            audio_base64 = base64.b64encode(notification_sound).decode()
            audio_html = f'<audio autoplay><source src="data:audio/wav;base64,{audio_base64}" type="audio/wav"></audio>'
            st.markdown(audio_html, unsafe_allow_html=True)

            # --- Merged Transcripts ---
            any_transcript_needed = any(
                v["download_transcript"] for v in videos_to_process
            )
            if any_transcript_needed:
                merged_transcript = ""
                for data in all_video_data:
                    if data.transcript:
                        merged_transcript += f"--- Transcription pour '{data.title}' ---\n"
                        merged_transcript += f"URL: {data.url}\n\n"
                        merged_transcript += data.transcript + "\n\n"

                st.subheader("Toutes les transcriptions")
                if merged_transcript:
                    st.download_button(
                        label="Télécharger toutes les transcriptions",
                        data=merged_transcript,
                        file_name="transcriptions_fusionnees.txt",
                        mime="text/plain",
                    )
                    st.text_area(
                        "Transcriptions fusionnées",
                        value=merged_transcript,
                        height=300,
                    )
                else:
                    st.warning("Aucune transcription n'a été trouvée.")

            # --- Merged Comments ---
            any_comments_needed = any(
                v["download_comments"] for v in videos_to_process
            )
            if any_comments_needed:
                merged_comments = ""
                for data in all_video_data:
                    if data.comments:
                        merged_comments += f"--- Commentaires pour '{data.title}' ---\n"
                        merged_comments += f"URL: {data.url}\n\n"
                        for comment in data.comments:
                            merged_comments += (
                                f"Auteur: {comment['author']}\n{comment['text']}\n\n"
                            )

                st.subheader("Tous les commentaires")
                if merged_comments:
                    st.download_button(
                        label="Télécharger tous les commentaires",
                        data=merged_comments,
                        file_name="commentaires_fusionnes.txt",
                        mime="text/plain",
                    )
                    st.text_area(
                        "Commentaires fusionnés",
                        value=merged_comments,
                        height=300,
                    )
                else:
                    st.warning("Aucun commentaire n'a été trouvé.")
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