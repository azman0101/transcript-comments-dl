"""
Streamlit Web App to Fetch YouTube Transcript and Comments
=========================================================

This Streamlit application provides a simple user interface for retrieving the
transcript (subtitles) and top‑level comments from a YouTube video.  It uses
the ``yt‑dlp`` Python module to download the comments and subtitles for a given
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
* **pysrt** (optional) – for parsing `.srt` subtitle files.  This module is
  listed in the ``requirements.txt`` file and can be installed along with
  Streamlit.

Once all dependencies are installed you can launch the app with:

```
streamlit run app.py
```

After starting, open the provided local URL in your browser and paste a YouTube
link to retrieve its transcript and comments.

Please note that fetching comments for popular videos can take a few minutes
depending on the number of comments available.
"""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import streamlit as st
from yt_dlp import YoutubeDL


def fetch_comments(video_url: str, work_dir: Path) -> List[str]:
    """Download and parse YouTube comments using yt‑dlp.

    yt‑dlp can extract comments directly when configured with appropriate options.
    We use the extract_info method to get video information including comments.

    Parameters
    ----------
    video_url:
        The full YouTube URL provided by the user.
    work_dir:
        A directory in which to store temporary files if needed.

    Returns
    -------
    List[str]
        A list of comment strings.  Only the textual content of each comment
        is returned.
    """
    # Derive a simple filename stem from the video URL by extracting the video
    # identifier.  This keeps file names short and avoids issues with special
    # characters in titles.
    video_id_match = re.search(r"(?<=v=)[^&?]+|(?<=youtu.be/)[^?&]+", video_url)
    if not video_id_match:
        raise ValueError("Impossible d'extraire l'identifiant de la vidéo.")
    video_id = video_id_match.group(0)

    # Configure yt-dlp options for extracting comments and info
    ydl_opts = {
        'skip_download': True,         # Don't download the video file
        'writecomments': True,         # Extract comments
        'writeinfojson': True,         # Write info to JSON to capture comments
        'outtmpl': str(work_dir / f"{video_id}"),  # Output template
        'quiet': True,                 # Reduce output noise
        'no_warnings': True,           # Suppress warnings in the logs
    }

    with YoutubeDL(ydl_opts) as ydl:
        try:
            # This will create a .info.json file with comments
            info_dict = ydl.extract_info(video_url, download=False)
        except Exception as e:
            raise RuntimeError(f"yt-dlp failed to extract video info: {str(e)}")

    # Check if we have comments in the info dict directly
    comments_raw = info_dict.get("comments") or []
    
    # If no comments in info dict, try to read from the JSON file
    if not comments_raw:
        json_path = work_dir / f"{video_id}.info.json"
        if json_path.exists():
            with json_path.open("r", encoding="utf-8") as f:
                info = json.load(f)
            comments_raw = info.get("comments") or []
    comments_text: List[str] = []
    for comment in comments_raw:
        # Some entries use the key "text", others use "txt".  We normalise
        # both.
        text = comment.get("text") or comment.get("txt") or ""
        if text:
            comments_text.append(text.strip())

    return comments_text


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

    # Configure yt-dlp options for extracting subtitles
    ydl_opts = {
        'skip_download': True,         # Don't download the video file
        'writesubtitles': True,        # Download manual subtitles
        'writeautomaticsub': True,     # Download auto-generated subtitles as fallback
        'subtitlesformat': 'srt',      # Request SRT format
        'subtitleslangs': [language],  # Request specific language
        'outtmpl': str(base_output),   # Output template
        'quiet': True,                 # Reduce output noise
        'no_warnings': True,           # Suppress warnings in the logs
    }

    with YoutubeDL(ydl_opts) as ydl:
        try:
            # This will download subtitle files to the work directory
            info_dict = ydl.extract_info(video_url, download=False)
        except Exception as e:
            raise RuntimeError(f"yt-dlp failed to extract video info: {str(e)}")

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
        ses commentaires.  Le traitement utilise le module Python `yt‑dlp` en interne.
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
        submitted = st.form_submit_button("Récupérer")

    if submitted:
        if not url:
            st.error("Merci de fournir une URL valide.")
            return
        try:
            with tempfile.TemporaryDirectory() as tmpdir_str:
                tmpdir = Path(tmpdir_str)
                with st.spinner("Téléchargement des commentaires..."):
                    comments = fetch_comments(url, tmpdir)
                with st.spinner("Téléchargement de la transcription..."):
                    actual_lang, transcript = fetch_transcript(url, tmpdir, lang)

                st.success("Récupération terminée !")

                # Display transcript
                if transcript:
                    st.subheader(f"Transcription ({actual_lang})")
                    st.text_area(
                        "Texte du transcript",
                        value=transcript,
                        height=300,
                    )
                    st.download_button(
                        label="Télécharger la transcription",
                        data=transcript,
                        file_name=f"{actual_lang}_transcript.txt",
                        mime="text/plain",
                    )
                else:
                    st.warning("Aucune transcription n'a été trouvée pour cette vidéo.")

                # Display comments
                if comments:
                    st.subheader(f"Commentaires ({len(comments)})")
                    # Show a sample of the first 100 comments to avoid overloading
                    max_display = 100
                    for idx, comment in enumerate(comments[:max_display], start=1):
                        st.markdown(f"**Commentaire {idx} :** {comment}")
                    if len(comments) > max_display:
                        st.info(
                            f"{len(comments) - max_display} autres commentaires non affichés."
                        )
                    # Prepare comments for download
                    comments_text = "\n".join(comments)
                    st.download_button(
                        label="Télécharger les commentaires",
                        data=comments_text,
                        file_name="comments.txt",
                        mime="text/plain",
                    )
                else:
                    st.warning("Aucun commentaire n'a pu être récupéré pour cette vidéo.")
        except Exception as exc:
            st.error(f"Une erreur est survenue : {exc}")


if __name__ == "__main__":
    main()