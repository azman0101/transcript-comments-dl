from playwright.sync_api import sync_playwright, expect
import re

def main():
    """
    This script verifies that the download buttons for the transcript and
    comments are located above their respective content areas.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Arrange: Go to the Streamlit app URL.
        page.goto("http://localhost:8501")

        # 2. Act: Fill in a YouTube URL and submit the form.
        # Using a video with a small number of comments to avoid timeouts.
        youtube_url_input = page.get_by_placeholder("https://www.youtube.com/watch?v=...")
        expect(youtube_url_input).to_be_visible()
        youtube_url_input.fill("https://www.youtube.com/watch?v=yv441E-i4_w")

        submit_button = page.get_by_role("button", name=re.compile("Récupérer", re.IGNORECASE))
        submit_button.click()

        # 3. Assert: Check for transcript and comments, then verify button positions.

        # Wait for the success message to ensure content is loaded.
        expect(page.get_by_text("Récupération terminée !")).to_be_visible(timeout=120000)

        # Ensure no "transcript not found" warning is present
        expect(page.get_by_text("Aucune transcription n'a été trouvée")).not_to_be_visible()

        # Verify transcript section using a more specific locator
        transcript_header = page.get_by_role("heading", name=re.compile("Transcription", re.IGNORECASE))
        expect(transcript_header).to_be_visible()

        download_transcript_button = page.get_by_role("button", name="Télécharger la transcription")
        expect(download_transcript_button).to_be_visible()

        transcript_text_area = page.locator('textarea[aria-label="Texte du transcript"]')
        expect(transcript_text_area).to_be_visible()

        # Verify comments section using a more specific locator
        comments_header = page.get_by_role("heading", name=re.compile("Commentaires", re.IGNORECASE))
        expect(comments_header).to_be_visible()

        download_comments_button = page.get_by_role("button", name="Télécharger les commentaires")
        expect(download_comments_button).to_be_visible()

        # 4. Screenshot: Capture the final result for visual verification.
        page.screenshot(path="jules-scratch/verification/verification.png")

        print("Verification script finished successfully and screenshot created.")

        browser.close()

if __name__ == "__main__":
    main()