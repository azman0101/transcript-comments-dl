from playwright.sync_api import sync_playwright, expect

def run_verification():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            # Navigate to the Streamlit app
            page.goto("http://localhost:8501", timeout=60000)

            # Wait for the app to load
            expect(page.get_by_text("Récupération de transcript et commentaires YouTube")).to_be_visible()

            # Input a YouTube URL
            page.get_by_placeholder("https://www.youtube.com/watch?v=...").fill("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

            # Uncheck the transcript download checkbox
            transcript_checkbox = page.get_by_text("Télécharger la transcription")
            transcript_checkbox.uncheck()

            # Click the "Récupérer" button
            page.get_by_role("button", name="Récupérer").click()

            # Wait for the results to load, with a longer timeout
            expect(page.get_by_text("Récupération terminée !")).to_be_visible(timeout=120000)

            # Take a screenshot
            page.screenshot(path="jules-scratch/verification/verification.png")

        finally:
            browser.close()

if __name__ == "__main__":
    run_verification()