"""LLM configuration utilities."""
from __future__ import annotations
import os
from pathlib import Path


def check_gemini_setup() -> tuple[bool, str]:
    """Check if Gemini API is properly configured.
    
    Returns:
        (is_configured, message)
    """
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        return False, (
            "Gemini API key is required for replicant to function.\n"
            "Get your API key from: https://aistudio.google.com/app/apikey\n"
            "Set it with: export GEMINI_API_KEY=your_api_key_here"
        )
    
    try:
        import google.genai as genai
    except ImportError:
        return False, "google-genai package not installed. Run: pip install google-genai"
    
    try:
        client = genai.Client(api_key=api_key)
        # Test the API with a simple call
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents="Hello"
        )
        return True, "Gemini API configured successfully - replicant is ready to use!"
    except Exception as e:
        return False, f"Gemini API test failed: {e}"


def get_config_instructions() -> str:
    """Get instructions for configuring Gemini API."""
    return """
🎆 Replicant: AI-Powered Research Environment Setup

Replicant uses Google's Gemini AI to intelligently analyze research papers and 
automatically create working environments. This provides:

• Smart GitHub repository detection
• Intelligent framework and library identification  
• Advanced dataset recognition
• Context-aware hardware requirement extraction
• Intelligent download URL classification

Setup:
1. Get a Gemini API key: https://aistudio.google.com/app/apikey
2. Set environment variable: export GEMINI_API_KEY=your_key_here
3. Run replicant normally - it will use AI analysis automatically

Without a valid API key, replicant cannot function.
"""