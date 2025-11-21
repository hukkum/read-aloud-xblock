import json
import requests

from web_fragments.fragment import Fragment
from xblock.core import XBlock
from xblock.fields import Scope, String, Float


HTML_TEMPLATE = """
<div class="pte-read-aloud">
  <style>
    .pte-read-aloud {{
      border: 1px solid #ddd;
      padding: 16px;
      border-radius: 4px;
      font-family: Arial, sans-serif;
    }}
    .pte-read-aloud h3 {{
      margin-top: 0;
    }}
    .pte-instructions {{
      font-style: italic;
      margin-bottom: 12px;
    }}
    .pte-media img {{
      max-width: 100%;
      margin-bottom: 12px;
    }}
    .pte-media audio {{
      display: block;
      margin-bottom: 12px;
    }}
    .pte-reference {{
      background: #f9f9f9;
      padding: 10px;
      border-radius: 4px;
      margin-bottom: 12px;
    }}
    .pte-controls button {{
      margin-right: 8px;
    }}
    .pte-status {{
      margin-top: 8px;
      font-size: 0.9em;
      color: #555;
    }}
    .pte-score-box {{
      margin-top: 10px;
      font-weight: bold;
    }}
    .pte-feedback h4 {{
      margin-top: 16px;
      margin-bottom: 8px;
    }}
    .pte-word-table {{
      border-collapse: collapse;
      width: 100%;
      margin-top: 8px;
    }}
    .pte-word-table th,
    .pte-word-table td {{
      border: 1px solid #ccc;
      padding: 4px 6px;
      font-size: 0.85em;
      text-align: left;
    }}
    .pte-word-table th {{
      background: #f0f0f0;
    }}
  </style>

  <h3>{title}</h3>
  <p class="pte-instructions">{instructions}</p>

  {media_block}

  <div class="pte-reference">
    <strong>Text to read:</strong>
    <p>{reference_text}</p>
  </div>

  <div class="pte-controls">
    <button type="button" class="pte-start">🎤 Start Recording</button>
    <button type="button" class="pte-stop" disabled>⏹ Stop</button>
  </div>

  <div class="pte-status" id="pte-status">Ready.</div>

  <div class="pte-score-box">
    Last saved score:
    <span id="pte-last-score">{last_score}</span> / 90
  </div>

  <div class="pte-feedback" id="pte-feedback" style="display:none;"></div>
</div>
"""


JS_CODE = """
function PTEXBlock(runtime, element) {
    var startBtn    = element.querySelector('.pte-start');
    var stopBtn     = element.querySelector('.pte-stop');
    var statusEl    = element.querySelector('#pte-status');
    var scoreEl     = element.querySelector('#pte-last-score');
    var feedbackEl  = element.querySelector('#pte-feedback');

    var handlerUrl  = runtime.handlerUrl(element, 'submit_audio');

    var mediaRecorder = null;
    var chunks = [];

    function setStatus(text) {
        if (statusEl) {
            statusEl.textContent = text;
        }
    }

    function setScore(score) {
        if (scoreEl) {
            scoreEl.textContent = score.toFixed(1);
        }
    }

    function renderFeedback(feedback) {
        if (!feedbackEl) {
            return;
        }
        var html = '<h4>Detailed feedback</h4>';
        html += '<ul>';
        if (typeof feedback.pron_score !== 'undefined') {
            html += '<li>Pronunciation: ' + feedback.pron_score.toFixed(1) + '</li>';
        }
        if (typeof feedback.accuracy !== 'undefined') {
            html += '<li>Accuracy: ' + feedback.accuracy.toFixed(1) + '</li>';
        }
        if (typeof feedback.fluency !== 'undefined') {
            html += '<li>Fluency: ' + feedback.fluency.toFixed(1) + '</li>';
        }
        if (typeof feedback.prosody !== 'undefined') {
            html += '<li>Prosody: ' + feedback.prosody.toFixed(1) + '</li>';
        }
        if (typeof feedback.completeness !== 'undefined') {
            html += '<li>Completeness: ' + feedback.completeness.toFixed(1) + '</li>';
        }
        html += '</ul>';

        if (feedback.words && feedback.words.length) {
            html += '<table class="pte-word-table">';
            html += '<thead><tr><th>Word</th><th>Accuracy</th><th>Error</th></tr></thead><tbody>';
            feedback.words.forEach(function (w) {
                html += '<tr><td>' + w.word + '</td><td>' + w.accuracy + '</td><td>' + w.error + '</td></tr>';
            });
            html += '</tbody></table>';
        }

        feedbackEl.innerHTML = html;
        feedbackEl.style.display = 'block';
    }

    function sendForScoring(b64Audio) {
        setStatus('Uploading & scoring your answer...');

        var payload = {
            audio_base64: b64Audio
        };

        var headers = {
            'Content-Type': 'application/json'
        };

        if (runtime && runtime.csrfToken) {
            headers['X-CSRFToken'] = runtime.csrfToken;
        }

        fetch(handlerUrl, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(payload)
        })
        .then(function (response) {
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            return response.json();
        })
        .then(function (data) {
            if (data.status === 'ok') {
                setStatus('Answer scored successfully.');
                if (typeof data.score === 'number') {
                    setScore(data.score);
                }
                if (data.feedback) {
                    renderFeedback(data.feedback);
                }
            } else {
                setStatus('Error: ' + (data.message || 'Unknown error'));
            }
        })
        .catch(function (err) {
            console.error('PTEXBlock error:', err);
            setStatus('Network or server error while scoring.');
        });
    }

    startBtn.addEventListener('click', function () {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setStatus('Microphone access is not supported in this browser.');
            return;
        }

        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(function (stream) {
                chunks = [];
                mediaRecorder = new MediaRecorder(stream);

                mediaRecorder.ondataavailable = function (e) {
                    if (e.data && e.data.size > 0) {
                        chunks.push(e.data);
                    }
                };

                mediaRecorder.onstop = function () {
                    var blob = new Blob(chunks, { type: 'audio/webm' });
                    var reader = new FileReader();
                    reader.onloadend = function () {
                        var result = reader.result || '';
                        var base64 = result.split(',')[1];  // strip data:...;base64,
                        if (!base64) {
                            setStatus('Could not read recorded audio.');
                            return;
                        }
                        sendForScoring(base64);
                    };
                    reader.readAsDataURL(blob);
                };

                mediaRecorder.start();
                setStatus('Recording... speak now.');
                startBtn.disabled = true;
                stopBtn.disabled = false;
            })
            .catch(function (err) {
                console.error('Microphone error:', err);
                setStatus('Could not access microphone: ' + err.message);
            });
    });

    stopBtn.addEventListener('click', function () {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
        }
        stopBtn.disabled = true;
        startBtn.disabled = false;
    });
}
"""


class PTEXBlock(XBlock):
    """
    PTE Read Aloud XBlock with:
    - Studio-editable reference text, instructions, and optional image/audio prompt
    - Backend scoring via external Flask API
    - Gradebook score based on pronunciation score (0–90)
    """

    # ------------------------
    # Studio / content fields
    # ------------------------
    display_name = String(
        display_name="Component Title",
        default="PTE Read Aloud Practice",
        scope=Scope.settings,
        help="Title shown to learners and in Studio."
    )

    instructions = String(
        display_name="Instructions",
        default="Look at the text below. In 40 seconds, you must read this text aloud as naturally and clearly as possible. The microphone will stop after 3 seconds of silence.",
        scope=Scope.content,
        help="Instructions shown above the text."
    )

    reference_text = String(
        display_name="Reference Text",
        default="Globalization has significantly changed the modern economy.",
        scope=Scope.content,
        help="Text the learner must read aloud."
    )

    prompt_image_url = String(
        display_name="Prompt Image URL",
        default="",
        scope=Scope.content,
        help="Optional image URL to show above the text (leave blank for no image)."
    )

    prompt_audio_url = String(
        display_name="Prompt Audio URL",
        default="",
        scope=Scope.content,
        help="Optional audio URL (e.g., sample answer). Leave blank for none."
    )

    api_url = String(
        display_name="Scoring API URL",
        default="http://127.0.0.1:5001/api/pte/read-aloud",
        scope=Scope.settings,
        help="Backend scoring API endpoint."
    )

    weight = Float(
        display_name="Problem Weight",
        default=1.0,
        scope=Scope.settings,
        help="Score weight for this problem in the course grade."
    )

    # ------------------------
    # Learner state
    # ------------------------
    student_score = Float(
        default=0.0,
        scope=Scope.user_state,
        help="Last saved pronunciation score (0–90)."
    )
    student_feedback = String(
        default="",
        scope=Scope.user_state,
        help="Raw JSON feedback from scoring API."
    )
    student_words = String(
        default="[]",
        scope=Scope.user_state,
        help="Word-level feedback JSON."
    )

    # This tells Studio / LMS it can be graded
    has_score = True
    icon_class = "problem"
    editable_fields = (
        "display_name",
        "instructions",
        "reference_text",
        "prompt_image_url",
        "prompt_audio_url",
        "api_url",
        "weight",
    )

    # ------------------------
    # Views
    # ------------------------
    def student_view(self, context=None):
        """
        Main learner view: shows title, instructions, optional media, text, and recorder UI.
        """
        media_parts = []
        if self.prompt_image_url:
            media_parts.append(
                f'<div class="pte-media"><img src="{self.prompt_image_url}" '
                f'alt="PTE prompt image" /></div>'
            )
        if self.prompt_audio_url:
            media_parts.append(
                '<div class="pte-media">'
                f'<audio controls src="{self.prompt_audio_url}">'
                'Your browser does not support the audio element.'
                '</audio></div>'
            )
        media_block = "".join(media_parts)

        last = f"{self.student_score:.1f}" if self.student_score else "0.0"

        html = HTML_TEMPLATE.format(
            title=self.display_name,
            instructions=self.instructions,
            reference_text=self.reference_text,
            media_block=media_block,
            last_score=last,
        )

        frag = Fragment(html)
        frag.add_javascript(JS_CODE)
        frag.initialize_js("PTEXBlock")
        return frag

    # ------------------------
    # JSON handler called from JS
    # ------------------------
    @XBlock.json_handler
    def submit_audio(self, data, suffix=""):
        """
        Receives base64-encoded audio from browser, calls scoring API, stores score.
        """
        try:
            audio_b64 = data.get("audio_base64")
            if not audio_b64:
                return {"status": "error", "message": "No audio data received"}

            payload = {
                "reference_text": self.reference_text,
                "audio_base64": audio_b64,
            }

            resp = requests.post(self.api_url, json=payload, timeout=25)
            resp.raise_for_status()
            backend = resp.json()

            if "error" in backend:
                return {"status": "error", "message": backend.get("error")}

            pron = backend.get("pron_score") or backend.get("score") or 0.0

            # Persist to learner state
            self.student_score = float(pron)
            self.student_feedback = json.dumps(backend)
            self.student_words = json.dumps(backend.get("words", []))

            return {
                "status": "ok",
                "score": float(pron),
                "feedback": backend,
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------
    # Grading hooks
    # ------------------------
    def max_score(self):
        """
        Max PTE-style score (0–90). LMS uses this as the full mark.
        """
        return 90.0

    def get_score(self):
        """
        Return learner's current numeric score.
        """
        return float(self.student_score)

    def set_score(self, score):
        """
        (Optional) Allow LMS or overrides to set the score manually.
        """
        self.student_score = float(score)

    # ------------------------
    # Workbench scenario (for SDK only)
    # ------------------------
    @staticmethod
    def workbench_scenarios():
        """
        Simple scenario so it appears in the xblock-sdk workbench.
        """
        return [
            ("PTE Read Aloud Inline",
             "<ptexblock/>"),
        ]
