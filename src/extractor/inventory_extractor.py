import os
import pathlib

from google import genai
from google.genai import types

from config import settings
from models.inventory import GeminiReceiptContract


class InventoryExtractor:
    def __init__(self):
        api_key = settings.GEMINI_API_KEY.get_secret_value()
        if not api_key:
            raise ValueError("Missing critical GEMINI_API_KEY environment configuration variable.")
        self.client = genai.Client(api_key=api_key)

    def extract_structured_receipt(self, file_path: pathlib.Path) -> GeminiReceiptContract:
        """
        Accepts a file path to an image or PDF receipt, sends the raw file bytes
        directly to Gemini via Multimodal capabilities, and returns type-checked schema data.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Receipt image file not found at: {file_path}")

        # 1. Map file extensions to correct MIME type headers
        suffix = file_path.suffix.lower()
        if suffix in (".png", ".png"):
            mime_type = "image/png"
        elif suffix in (".jpg", ".jpeg"):
            mime_type = "image/jpeg"
        elif suffix == ".pdf":
            mime_type = "application/pdf"
        else:
            raise ValueError(f"Unsupported file format extension: {suffix}")

        # 2. Read file as bytes and wrap it for the SDK
        file_bytes = file_path.read_bytes()
        image_part = types.Part.from_bytes(
            data=file_bytes,
            mime_type=mime_type,
        )

        system_instruction = """
        You are a structured document parsing engine for 'Smartory', an automated inventory system.
        Your job is to visually inspect uploaded receipts or invoices and map them into structured inventory entries.
        
        Rules:
        1. Clean up messy or shortened shorthand item text names into recognizable household products along with the weight or quantity if present. If you are unsure with the name then  just extract the name as it is. Do not guess or hallucinate. For example if you see "Sonntagsbr.330g" either you extract as it is or you do Sonntagsbrötchen 330g not Sunday roast.
        2. Assign accurate categories and storage conditions based on common culinary/household knowledge. 
        3. Infer shelf life based on the item type (e.g., Fresh milk in 'Kept Cool' -> ~7 days, Eggs -> ~14 days, Canned goods -> Null). Chicken, fish, shrimps and other meats are usually kept frozen and have a shelf life of around 6 months. Electronics, hardware and non-perishables should have null shelf life.
        4. Match all outputs exactly against the required JSON schema structures.
        """

        # Update the prompt text since the model can look at the image directly
        prompt = "Please analyze this receipt image and extract all store metadata parameters and granular line items."

        try:
            # Pass the image part directly in the contents list along with the text prompt
            response = self.client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=[image_part, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=GeminiReceiptContract,
                ),
            )

            return GeminiReceiptContract.model_validate_json(response.text)

        except Exception as e:
            print(f"[Gemini Multimodal Extraction Error] Validation failure: {str(e)}")
            raise e
