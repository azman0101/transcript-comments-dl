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
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import streamlit as st


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


def fetch_comments(video_url: str, work_dir: Path) -> List[str]:
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


def fetch_transcript(video_url: str, work_dir: Path, language: str = "auto") -> Tuple[str, str]:
    """Download and parse YouTube subtitles using yt‑dlp.

    yt‑dlp will attempt to download manually provided subtitles first and fall
    back to automatically generated subtitles when ``--write-auto-subs`` is
    specified.  We request subtitles in the desired language and fall back to
    the best available language if auto-detect is selected or if the specified
    language is not available.

    Parameters
    ----------
    video_url:
        The YouTube URL.
    work_dir:
        Temporary directory used to store the downloaded subtitle file.
    language:
        Two‑letter language code (e.g. "fr" for French, "en" for English)
        or "auto" for automatic language detection.

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

    # If auto-detect is selected, get all available languages
    if language == "auto":
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-sub",
            "--write-auto-subs",
            "--sub-format",
            "srt",
            "--all-subs",
            "-o",
            str(base_output),
            video_url,
        ]
    else:
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
    
    if language == "auto":
        # Priority order for auto-detection
        priority_languages = ["en", "fr", "es", "de", "it", "pt", "ja", "ko", "zh", "ru"]
        
        # First, try to find a language from our priority list
        for preferred_lang in priority_languages:
            for file in possible_files:
                suffix_parts = file.name.split(".")
                if len(suffix_parts) >= 3:
                    lang_code = suffix_parts[-2]
                    if lang_code == preferred_lang:
                        subtitle_path = file
                        selected_lang = lang_code
                        break
            if subtitle_path:
                break
        
        # If no priority language found, use the first available
        if subtitle_path is None and possible_files:
            subtitle_path = possible_files[0]
            parts = subtitle_path.name.split(".")
            selected_lang = parts[-2] if len(parts) >= 3 else "unknown"
    else:
        # Look for the specific requested language
        for file in possible_files:
            suffix_parts = file.name.split(".")
            if len(suffix_parts) >= 3:
                lang_code = suffix_parts[-2]
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


def get_language_options():
    """Get available language options for transcript download.
    
    Returns
    -------
    Dict[str, str]
        A dictionary mapping language codes to display names.
    """
    return {
        "auto": "Auto-detect (best available)",
        "fr": "Français (French)",
        "en": "English", 
        "es": "Español (Spanish)",
        "de": "Deutsch (German)",
        "it": "Italiano (Italian)",
        "pt": "Português (Portuguese)",
        "ja": "日本語 (Japanese)",
        "ko": "한국어 (Korean)",
        "zh": "中文 (Chinese)",
        "ru": "Русский (Russian)",
        "ar": "العربية (Arabic)",
        "hi": "हिन्दी (Hindi)",
        "nl": "Nederlands (Dutch)",
        "sv": "Svenska (Swedish)",
        "no": "Norsk (Norwegian)",
        "da": "Dansk (Danish)",
        "fi": "Suomi (Finnish)",
        "pl": "Polski (Polish)",
        "tr": "Türkçe (Turkish)"
    }


def get_language_display_name(lang_code: str) -> str:
    """Get the display name for a language code.
    
    Parameters
    ----------
    lang_code : str
        The language code (e.g., 'fr', 'en', 'es')
    
    Returns
    -------
    str
        The display name for the language, or the code itself if not found.
    """
    language_options = get_language_options()
    return language_options.get(lang_code, lang_code.upper())


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
        
        ### 🌍 Sélection de langue
        - **Auto-detect** : Télécharge automatiquement la meilleure langue disponible
        - **Langue spécifique** : Télécharge dans la langue demandée ou se rabat sur une alternative
        - Supporte plus de 20 langues incluant les sous-titres automatiques et manuels
        """
    )

    language_options = get_language_options()

    with st.form("input_form"):
        url = st.text_input(
            "Lien de la vidéo YouTube", placeholder="https://www.youtube.com/watch?v=..."
        )
        
        lang_display = st.selectbox(
            "Langue des sous‑titres",
            options=list(language_options.values()),
            index=0,
            help="""
            Choisissez la langue à privilégier pour les sous‑titres:
            • Auto-detect: Télécharge la meilleure langue disponible (recommandé)
            • Langue spécifique: Tente de télécharger dans cette langue, sinon utilise une alternative
            • Supporte les sous-titres manuels et automatiques de YouTube
            """
        )
        
        # Get the language code from the selected display name
        lang = next(code for code, name in language_options.items() if name == lang_display)
        
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

                # Get language display name for better UX
                actual_lang_display = get_language_display_name(actual_lang)

                # Display transcript
                if transcript:
                    st.subheader(f"Transcription ({actual_lang_display})")
                    
                    # Add info about language selection
                    if lang == "auto":
                        st.info(f"🎯 Langue automatiquement détectée : **{actual_lang_display}**")
                    elif actual_lang != lang:
                        requested_lang_display = get_language_display_name(lang)
                        st.warning(f"⚠️ Langue demandée ({requested_lang_display}) non disponible. Utilisation de : **{actual_lang_display}**")
                    else:
                        st.success(f"✅ Transcription récupérée en : **{actual_lang_display}**")
                    
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
                    if lang == "auto":
                        st.warning("Aucune transcription n'a été trouvée pour cette vidéo dans aucune langue.")
                    else:
                        requested_lang_display = get_language_display_name(lang)
                        st.warning(f"Aucune transcription n'a été trouvée pour cette vidéo en {requested_lang_display}. Essayez l'option 'Auto-detect' pour voir si d'autres langues sont disponibles.")

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