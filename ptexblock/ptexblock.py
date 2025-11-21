import json
import requests

from web_fragments.fragment import Fragment
from xblock.core import XBlock
from xblock.fields import Scope, String, Float
from xblock.fragment import Fragment


class PTEXBlock(XBlock):
    """
    PTE Read Aloud XBlock
    - Student can record an answer and get AI feedback.
    - Instructor can edit title / instructions / reference text in Studio.
    """

    # ---------- Instructor-editable content ----------
    title = String(
        default="PTE Read Aloud Practice",
        scope=Scope.content,
        help="Title shown to the learner."
    )

    instructions = String(
        default=(
            'Look at the text below. In 40 seconds, you must read this text aloud '
            'as naturally and clearly as possible. You have 40 seconds to read aloud. '
            'The microphone will stop after 3 seconds of silence!'
        ),
        scope=Scope.content,
        help="Instructions displayed above the reference text."
    )

    reference_text = String(
        default="Globalization has significantly changed the modern economy.",
        scope=Scope.content,
        help="The text the learner must read aloud."
    )

    # Scoring API endpoint (override per course/site if needed)
    api_url = String(
        default="http://127.0.0.1:5001/api/pte/read-aloud",
        scope=Scope.settings,
        help="Backend API endpoint for pronunciation scoring."
    )

    # ---------- Per-learner state ----------
    student_score = Float(
        default=0.0,
        scope=Scope.user_state,
        help="Latest pronunciation score for this learner."
    )

    student_feedback = String(
        default="",
        scope=Scope.user_state,
        help="Raw JSON feedback from the scoring API."
    )

    # ---------- Student view ----------
    def student_view(self, context=None):
        """
        Main learner view: shows instructions, text, and record/stop controls.
        """
        last_score_text = (
            f"{self.student_score:.1f}"
            if self.student_score and self.student_score > 0
            else "No score yet"
        )

        html = f"""
        <div class="pte-read-aloud" id="pte-read-aloud-{{id}}">
          <h2>{self.title}</h2>
          <p class="pte-instructions">{self.instructions}</p>

          <p><strong>Read the following text aloud:</strong></p>
          <div class="pte-reference-text">
            {self.reference_text}
          </div>

          <div class="pte-controls">
            <button class="pte-start">🎤 Start Recording</button>
            <button class="pte-stop" disabled>⏹ Stop</button>
          </div>

          <p class="pte-status">Press "Start Recording" to begin.</p>

          <div class="pte-last-score">
            <strong>Last saved score:</strong> <span class="pte-last-score-value">{last_score_text}</span>
          </div>

          <pre class="pte-debug-log" style="display:none;"></pre>
        </div>
        """

        frag = Fragment(html)
        frag.add_javascript(self._student_js())
        frag.add_css(self._student_css())
        frag.initialize_js('PTEXBlockStudent')
        return frag

    # ---------- Student JS/CSS (inline to avoid packaging issues) ----------
    def _student_js(self):
        """
        Inline JavaScript for the student view.
        Uses MediaRecorder to capture audio and send it as base64 to submit_audio handler.
        """
        return r"""
        function PTEXBlockStudent(runtime, element) {
            var $element = $(element);
            var startBtn = $element.find('.pte-start');
            var stopBtn = $element.find('.pte-stop');
            var statusEl = $element.find('.pte-status');
            var lastScoreEl = $element.find('.pte-last-score-value');
            var debugLog = $element.find('.pte-debug-log');

            var mediaRecorder = null;
            var chunks = [];

            function logDebug(msg, obj) {
                console.log("PTEXBlock:", msg, obj || "");
                var existing = debugLog.text();
                debugLog.text(existing + "\n" + msg + (obj ? (" " + JSON.stringify(obj)) : ""));
            }

            function setStatus(text) {
                statusEl.text(text);
            }

            function enableRecording(enabled) {
                startBtn.prop('disabled', !enabled);
                stopBtn.prop('disabled', enabled);
            }

            startBtn.on('click', function() {
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    setStatus("Your browser does not support audio recording.");
                    return;
                }

                navigator.mediaDevices.getUserMedia({ audio: true })
                    .then(function(stream) {
                        mediaRecorder = new MediaRecorder(stream);
                        chunks = [];

                        mediaRecorder.ondataavailable = function(e) {
                            if (e.data && e.data.size > 0) {
                                chunks.push(e.data);
                            }
                        };

                        mediaRecorder.onstop = function() {
                            setStatus("Uploading & scoring your answer...");
                            var blob = new Blob(chunks, { type: 'audio/webm' });

                            var reader = new FileReader();
                            reader.onloadend = function() {
                                var base64data = reader.result.split(',')[1]; // strip data URL prefix
                                sendToServer(base64data);
                            };
                            reader.readAsDataURL(blob);
                        };

                        mediaRecorder.start();
                        enableRecording(false);
                        setStatus("Recording... Speak now.");
                    })
                    .catch(function(err) {
                        console.error("getUserMedia error:", err);
                        setStatus("Could not access microphone: " + err.message);
                    });
            });

            stopBtn.on('click', function() {
                if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                    mediaRecorder.stop();
                    enableRecording(true);
                    setStatus("Processing your answer...");
                }
            });

            function sendToServer(audioBase64) {
                var handlerUrl = runtime.handlerUrl(element, 'submit_audio');
                logDebug("Sending audio to handler...", { url: handlerUrl });

                $.ajax({
                    type: "POST",
                    url: handlerUrl,
                    data: JSON.stringify({ audio_base64: audioBase64 }),
                    contentType: "application/json",
                }).done(function(response) {
                    logDebug("API response:", response);

                    if (response.status === "ok") {
                        setStatus("Answer successfully submitted and scored.");
                        if (response.score !== undefined && response.score !== null) {
                            lastScoreEl.text(response.score.toFixed(1));
                        }
                    } else {
                        setStatus("Error: " + (response.message || "Unknown error"));
                    }
                }).fail(function(jqXHR, textStatus, errorThrown) {
                    console.error("AJAX error:", textStatus, errorThrown);
                    setStatus("Network/Server error while scoring your answer.");
                });
            }
        }
        """

    def _student_css(self):
        """
        Minimal CSS to keep things readable.
        """
        return r"""
        .pte-read-aloud {
            border: 1px solid #ddd;
            padding: 16px;
            border-radius: 4px;
            margin: 10px 0;
        }
        .pte-reference-text {
            border: 1px dashed #ccc;
            padding: 8px;
            margin-bottom: 12px;
            background: #fafafa;
        }
        .pte-controls button {
            margin-right: 8px;
        }
        .pte-status {
            margin-top: 8px;
            font-style: italic;
        }
        .pte-last-score {
            margin-top: 10px;
        }
        """

    # ---------- Handler called by JS ----------
    @XBlock.json_handler
    def submit_audio(self, data, suffix=''):
        """
        Receives base64 audio from JS, sends it to the scoring API, stores score.
        """
        audio_b64 = data.get("audio_base64")
        if not audio_b64:
            return {"status": "error", "message": "No audio provided"}

        payload = {
            "reference_text": self.reference_text,
            "audio_base64": audio_b64,
        }

        try:
            resp = requests.post(
                self.api_url,
                json=payload,
                timeout=30
            )
        except Exception as e:
            return {"status": "error", "message": f"Backend API error: {e}"}

        try:
            result = resp.json()
        except Exception:
            return {
                "status": "error",
                "message": f"Invalid JSON from backend (status {resp.status_code})",
            }

        if "error" in result:
            return {"status": "error", "message": result.get("error", "Unknown error")}

        # Save learner state
        pron_score = float(result.get("pron_score", 0.0))
        self.student_score = pron_score
        self.student_feedback = json.dumps(result)

        return {
            "status": "ok",
            "score": pron_score,
            "feedback": result,
        }

    # ---------- Gradebook hooks (we'll refine later) ----------
    def max_score(self):
        # PTE is out of 90; for now we just mirror that conceptually.
        return 90.0

    def get_score(self):
        # LMS will use this when grading the problem.
        return float(self.student_score or 0.0)

    # ---------- Studio authoring view ----------
    def studio_view(self, context=None):
        """
        Simple Studio editor to let instructors edit title, instructions, and reference text.
        """
        html = f"""
        <div class="pte-studio-editor">
          <div class="field">
            <label>Title</label><br/>
            <input type="text" name="title" value="{self.title}" style="width: 100%;" />
          </div>

          <div class="field" style="margin-top: 10px;">
            <label>Instructions</label><br/>
            <textarea name="instructions" rows="3" style="width: 100%;">{self.instructions}</textarea>
          </div>

          <div class="field" style="margin-top: 10px;">
            <label>Reference text</label><br/>
            <textarea name="reference_text" rows="6" style="width: 100%;">{self.reference_text}</textarea>
          </div>

          <div class="actions" style="margin-top: 15px;">
            <button class="btn btn-primary save-button">Save</button>
            <button class="btn cancel-button">Cancel</button>
          </div>
        </div>
        """

        frag = Fragment(html)
        frag.add_javascript(self._studio_js())
        frag.initialize_js('PTEXBlockStudio')
        return frag

    def _studio_js(self):
        """
        Inline JS for Studio editor (save/cancel, calls studio_submit handler).
        """
        return r"""
        function PTEXBlockStudio(runtime, element) {
            var $element = $(element);

            var $title = $element.find('input[name=title]');
            var $instructions = $element.find('textarea[name=instructions]');
            var $reference = $element.find('textarea[name=reference_text]');

            var saveBtn = $element.find('.save-button');
            var cancelBtn = $element.find('.cancel-button');

            var handlerUrl = runtime.handlerUrl(element, 'studio_submit');

            saveBtn.on('click', function (e) {
                e.preventDefault();

                var data = {
                    title: $title.val(),
                    instructions: $instructions.val(),
                    reference_text: $reference.val()
                };

                runtime.notify('save', {state: 'start'});

                $.ajax({
                    type: "POST",
                    url: handlerUrl,
                    data: JSON.stringify(data),
                    contentType: "application/json"
                }).done(function (response) {
                    runtime.notify('save', {state: 'end'});
                }).fail(function () {
                    runtime.notify('error', {
                        msg: "Error saving settings."
                    });
                });
            });

            cancelBtn.on('click', function (e) {
                e.preventDefault();
                runtime.notify('cancel', {});
            });
        }
        """

    @XBlock.json_handler
    def studio_submit(self, data, suffix=''):
        """
        Save changes from Studio editor.
        """
        self.title = data.get('title', self.title)
        self.instructions = data.get('instructions', self.instructions)
        self.reference_text = data.get('reference_text', self.reference_text)
        return {"result": "success"}

    # ---------- Workbench scenario for the SDK ----------
    @staticmethod
    def workbench_scenarios():
        """
        So it shows up as <ptexblock/> in the SDK.
        """
        return [
            ("PTE Read Aloud simple scenario",
             "<ptexblock/>"),
        ]
