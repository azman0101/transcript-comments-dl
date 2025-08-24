"""
Streamlit Web App to Fetch YouTube Transcript and Comments
=========================================================

This Streamlit application provides a simple user interface for retrieving the
transcript (subtitles) and top‑level comments from a YouTube video.  It uses
the ``yt‑dlp`` Python module to download the comments and subtitles for a given
video URL.  The resulting transcript and comments are displayed directly in
the browser and can optionally be downloaded as plain text files.

This version includes multiple fallback strategies to handle YouTube's bot
detection and authentication requirements.

Requirements
------------

To run this application you must have the following tools installed on your
machine:

* **Python 3.8 or newer**
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
    """Download and parse YouTube comments using yt‑dlp with bot detection workarounds.

    This function implements multiple fallback strategies to handle YouTube's
    bot detection and authentication requirements.

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

    # Multiple approaches to try in case of YouTube bot detection
    approaches = [
        # Approach 1: Use Chrome browser cookies
        {
            'skip_download': True,
            'writecomments': True,
            'writeinfojson': True,
            'outtmpl': str(work_dir / f"{video_id}"),
            'quiet': True,
            'no_warnings': True,
            'cookiesfrombrowser': ('chrome',),
        },
        # Approach 2: Use Firefox browser cookies
        {
            'skip_download': True,
            'writecomments': True,
            'writeinfojson': True,
            'outtmpl': str(work_dir / f"{video_id}"),
            'quiet': True,
            'no_warnings': True,
            'cookiesfrombrowser': ('firefox',),
        },
        # Approach 3: Custom headers to simulate real browser
        {
            'skip_download': True,
            'writecomments': True,
            'writeinfojson': True,
            'outtmpl': str(work_dir / f"{video_id}"),
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
        },
        # Approach 4: YouTube extractor arguments
        {
            'skip_download': True,
            'writecomments': True,
            'writeinfojson': True,
            'outtmpl': str(work_dir / f"{video_id}"),
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv', 'web', 'ios'],
                    'skip': ['hls', 'dash'],
                }
            }
        },
        # Approach 5: Basic configuration (last resort)
        {
            'skip_download': True,
            'writecomments': True,
            'writeinfojson': True,
            'outtmpl': str(work_dir / f"{video_id}"),
            'quiet': True,
            'no_warnings': True,
        }
    ]

    last_error = None

    for approach_num, ydl_opts in enumerate(approaches, 1):
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=False)

            # Check if we have comments in the info dict directly
            comments_raw = info_dict.get("comments") or []

            # If no comments in info dict, try to read from the JSON file
            if not comments_raw:
                json_path = work_dir / f"{video_id}.info.json"
                if json_path.exists():
                    with json_path.open("r", encoding="utf-8") as f:
                        info = json.load(f)
                    comments_raw = info.get("comments") or []

            # Extract text from comments
            comments_text: List[str] = []
            for comment in comments_raw:
                # Some entries use the key "text", others use "txt".  We normalise
                # both.
                text = comment.get("text") or comment.get("txt") or ""
                if text:
                    comments_text.append(text.strip())

            return comments_text

        except Exception as e:
            last_error = e
            error_msg = str(e)

            # If it's not the bot detection error, re-raise immediately
            if "Sign in to confirm" not in error_msg and "bot" not in error_msg.lower():
                raise RuntimeError(f"yt-dlp failed to extract video info: {str(e)}")

            # Otherwise, continue to next approach
            continue

    # If all approaches failed, raise the last error with context
    raise RuntimeError(f"Failed to extract comments after trying {len(approaches)} approaches. "
                      f"YouTube may be blocking access. Last error: {last_error}")


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
    """Download and parse YouTube subtitles using yt‑dlp with bot detection workarounds.

    This function implements multiple fallback strategies to handle YouTube's
    bot detection and authentication requirements when fetching subtitles.

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

    # Multiple approaches to try in case of YouTube bot detection
    approaches = [
        # Approach 1: Use Chrome browser cookies
        {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitlesformat': 'srt',
            'subtitleslangs': [language],
            'outtmpl': str(base_output),
            'quiet': True,
            'no_warnings': True,
            'cookiesfrombrowser': ('chrome',),
        },
        # Approach 2: Use Firefox browser cookies
        {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitlesformat': 'srt',
            'subtitleslangs': [language],
            'outtmpl': str(base_output),
            'quiet': True,
            'no_warnings': True,
            'cookiesfrombrowser': ('firefox',),
        },
        # Approach 3: Custom headers to simulate real browser
        {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitlesformat': 'srt',
            'subtitleslangs': [language],
            'outtmpl': str(base_output),
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
        },
        # Approach 4: YouTube extractor arguments
        {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitlesformat': 'srt',
            'subtitleslangs': [language],
            'outtmpl': str(base_output),
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv', 'web', 'ios'],
                    'skip': ['hls', 'dash'],
                }
            }
        },
        # Approach 5: Basic configuration (last resort)
        {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitlesformat': 'srt',
            'subtitleslangs': [language],
            'outtmpl': str(base_output),
            'quiet': True,
            'no_warnings': True,
        }
    ]

    last_error = None

    for approach_num, ydl_opts in enumerate(approaches, 1):
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=False)

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

        except Exception as e:
            last_error = e
            error_msg = str(e)

            # If it's not the bot detection error, re-raise immediately
            if "Sign in to confirm" not in error_msg and "bot" not in error_msg.lower():
                raise RuntimeError(f"yt-dlp failed to extract video info: {str(e)}")

            # Otherwise, continue to next approach
            continue

    # If all approaches failed, return empty result with warning
    return language, ""


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

        ⚠️ **Note importante :** YouTube a récemment renforcé ses protections anti-bot.
        Si vous rencontrez des erreurs, voici les solutions :

        1. **Connectez-vous à YouTube dans votre navigateur** (Chrome ou Firefox)
        2. **Essayez avec des vidéos moins populaires**
        3. **Attendez quelques minutes entre les tentatives**

        L'application essaiera automatiquement plusieurs méthodes pour contourner ces restrictions.
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
            error_msg = str(exc)
            if "Sign in to confirm" in error_msg or "bot" in error_msg.lower():
                st.error("❌ YouTube a détecté une activité automatisée")
                st.markdown("""
                **Solutions recommandées :**

                1. **Connectez-vous à YouTube** dans votre navigateur (Chrome ou Firefox)
                2. **Réessayez dans quelques minutes**
                3. **Utilisez une vidéo différente** (moins populaire)
                4. **Vérifiez votre connexion internet**

                Cette erreur est temporaire et liée aux protections anti-bot de YouTube.
                """)
            elif "Failed to extract comments after trying" in error_msg:
                st.error("❌ Impossible de récupérer les données après plusieurs tentatives")
                st.markdown("""
                **Que s'est-il passé ?**

                L'application a essayé plusieurs méthodes pour contourner les protections YouTube,
                mais toutes ont échoué. Ceci peut arriver avec des vidéos très populaires ou
                lorsque YouTube renforce temporairement ses restrictions.

                **Solutions :**

                1. Réessayez avec une autre vidéo
                2. Attendez 10-15 minutes avant de réessayer
                3. Vérifiez que l'URL est correcte et que la vidéo est publique
                """)
            else:
                st.error(f"Une erreur est survenue : {exc}")
                st.markdown("""
                **Aide au débogage :**

                Si cette erreur persiste, vérifiez :
                - L'URL YouTube est correcte
                - La vidéo est publique (pas privée ou supprimée)
                - Votre connexion internet fonctionne
                """)

            # Afficher les détails techniques en cas de besoin
            with st.expander("Détails techniques de l'erreur"):
                st.code(str(exc))


if __name__ == "__main__":
    main()
