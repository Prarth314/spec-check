"""Select a stateless hosted workspace without writing to the deployment bundle."""
import os


def browser_storage():
    return os.getenv("VERCEL") == "1" or os.getenv("SPEC_CHECK_HOSTED") == "1"
