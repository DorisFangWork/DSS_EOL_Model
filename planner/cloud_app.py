"""Community Cloud entry point: synthetic inputs and session/download outputs only.

Access control is configured separately in Streamlit Community Cloud Sharing.
"""

from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("app.py")),
               init_globals={"SYNTHETIC_CLOUD": True}, run_name="__main__")
