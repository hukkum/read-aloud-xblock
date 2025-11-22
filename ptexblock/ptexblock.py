import json
from pathlib import Path

import requests
from web_fragments.fragment import Fragment
from xblock.core import XBlock
from xblock.exceptions import JsonHandlerError
from xblock.fields import Scope, String, Float


class PTEXBlock(XBlock):
    """
    PTE Read Aloud XBlock (SDK-friendly version)

    - Instructor fields: title, instructions, reference_text, api_url
    - Student records audio -> sent to backend API -> score stored in user_state
    """

    # ---------- Instructor-editable fields ----------
    title = String(
        default="PTE Read Aloud Practice",
        scope=Scope.content,
        help="Title shown to learners.",
    )

    instructions = String(
        default=(
            "Look at the text below. In 40 seconds, you must read this text "
            "aloud as naturally and clearly as possible. The microphone will "
            "stop after 3 seconds of silence!"
        ),
        scope=Scope.content,
        help="Instructions shown above the text.",
    )

    reference_text = String(
        default="Globalization has significantly changed the modern economy.",
        scope=Scope.content,
        help="Text that the learner must read aloud.",
    )

    api_url = String(
        # point this to your local or prod API
        default="http://127.0.0.1:5001/api/pte/read-aloud",
        scope=Scope.settings,
        help="Backend API endpoint for pronunciation scoring.",
    )

    # ---------- Per-learner state ----------
    student_score = Float(
        default=0.0,
        scope=Scope.user_state,
        help="Last pronunciation score returned by the API.",
    )

    student_feedback = String(
        default="",
        scope=Scope.user_state,
        help="Raw JSON feedback from the scoring API (as string).",
    )

    # ---------- Resource loader (FIXES FileNotFound) ----------
    def resource_string(self, path: str) -> str:
        """
        Load a static file relative to this python file.

        This makes the path:
          <repo>/ptexblock/ptexblock/ + path
        so "static/html/ptexblock.html" ends up at
          <repo>/ptexblock/ptexblock/static/html/ptexblock.html
        """
        here = Path(__file__).parent  # .../ptexblock/ptexblock
        return (here / path).read_text(encoding="utf-8")

    # ---------- Student view ----------
    def student_view(self, context=None):
        """
        Main learner-facing view.
        """
        # Load HTML template
        html = self.resource_string("static/html/ptexblock.html")

        # Allow {self.title}, {self.instructions}, {self.reference_text} in HTML
        html = html.format(self=self)

        frag = Fragment(html)
        frag.add_css(self.resource_string("static/css/ptexblock.css"))
        frag.add_javascript(self.resource_string("static/js/src/ptexblock.js"))
        frag.initialize_js("PTEXBlock")
        return frag

    # ---------- AJAX handler ----------
    @XBlock.json_handler
    def submit_audio(self, data, suffix=""):
        """
        Called from JS with base64 audio.
        Expects:
            { "audio_base64": "data:audio/webm;base64,...." }
        """
        audio_base64 = data.get("audio_base64")
        if not audio_base64:
            raise JsonHandlerError(400, "Missing audio data")

        payload = {
            "reference_text": self.reference_text,
            "audio_base64": audio_base64,
        }

        try:
            resp = requests.post(self.api_url, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            raise JsonHandlerError(500, f"Error calling scoring API: {e!s}")

        pron_score = result.get("pron_score")
        if pron_score is None:
            raise JsonHandlerError(500, f"Invalid API response: {result}")

        # Save state
        self.student_score = float(pron_score)
        self.student_feedback = json.dumps(result)

        return {
            "status": "ok",
            "score": self.student_score,
            "feedback": result,
        }

    # ---------- Grading hooks ----------
    def max_score(self):
        return 90.0

    def get_score(self):
        return self.student_score

    def set_score(self, score):
        self.student_score = float(score)

    # ---------- Workbench scenario ----------
    @staticmethod
    def workbench_scenarios():
        return [
            (
                "PTE Read Aloud - Single",
                "<vertical_demo><ptexblock/></vertical_demo>",
            ),
        ]
