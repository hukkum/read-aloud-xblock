function PTEXBlock(runtime, element) {
var $element    = $(element);

var $startBtn   = $element.find('.pte-start');
var $stopBtn    = $element.find('.pte-stop');
var $status     = $element.find('#pte-status');
var $lastScore  = $element.find('#pte-last-score');
var $feedbackBox = $element.find('#pte-feedback');
var $wordsBody  = $element.find('#pte-words-table tbody');

var mediaRecorder = null;
var recordedChunks = [];
var stream = null;

function setStatus(text) {
    $status.text(text);
}

function resetRecording() {
    recordedChunks = [];
}

function startRecording() {
    if (mediaRecorder && mediaRecorder.state === "recording") {
        return;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setStatus("Microphone is not supported in this browser.");
        return;
    }

    navigator.mediaDevices.getUserMedia({ audio: true })
        .then(function (s) {
            stream = s;
            mediaRecorder = new MediaRecorder(stream);
            resetRecording();

            mediaRecorder.ondataavailable = function (e) {
                if (e.data && e.data.size > 0) {
                    recordedChunks.push(e.data);
                }
            };

            mediaRecorder.onstop = function () {
                var blob = new Blob(recordedChunks, { type: 'audio/webm' });
                var reader = new FileReader();

                reader.onloadend = function () {
                    var dataUrl = reader.result; // data:audio/webm;base64,....
                    sendForScoring(dataUrl);
                };

                reader.readAsDataURL(blob);

                if (stream) {
                    stream.getTracks().forEach(function (t) { t.stop(); });
                    stream = null;
                }
            };

            mediaRecorder.start();
            $startBtn.prop('disabled', true);
            $stopBtn.prop('disabled', false);
            setStatus("Recording... Speak clearly.");
        })
        .catch(function (err) {
            console.error("getUserMedia error:", err);
            setStatus("Unable to access microphone: " + err.message);
        });
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
        $startBtn.prop('disabled', false);
        $stopBtn.prop('disabled', true);
        setStatus("Uploading & scoring your answer...");
    }
}

function sendForScoring(audioDataUrl) {
    var handlerUrl = runtime.handlerUrl(element, 'submit_audio');

    $.ajax({
        type: "POST",
        url: handlerUrl,
        data: JSON.stringify({
            audio_base64: audioDataUrl
        }),
        contentType: "application/json",
        dataType: "json",
        success: function (response) {
            console.log("API response:", response);

            if (!response || response.status !== "ok") {
                setStatus("Error: " + (response && response.message ? response.message : "Unknown error"));
                return;
            }

            setStatus("Answer submitted and scored. You can retry to improve your score.");

            // Overall block score (0–90) from backend
            var score = response.score || 0;
            if (typeof score === "number") {
                $lastScore.text(score.toFixed(1));
            } else {
                $lastScore.text(score);
            }

            var fb = response.feedback || {};
            $feedbackBox.show();

            // Raw metrics coming from Flask backend
            var pron = fb.pron_score;
            var acc  = fb.accuracy;
            var flu  = fb.fluency;
            var pro  = fb.prosody;
            var comp = fb.completeness;

            // --- PTE 3-criterion mapping ---
            // Content: average of accuracy and completeness (simple heuristic)
            var contentScore = null;
            if (typeof acc === "number" && typeof comp === "number") {
                contentScore = (acc + comp) / 2.0;
            }

            $element.find('#pte-summary-content').text(
                (typeof contentScore === "number") ? contentScore.toFixed(1) : '–'
            );
            $element.find('#pte-summary-fluency-main').text(
                (typeof flu === "number") ? flu.toFixed(1) : '–'
            );
            $element.find('#pte-summary-pron-main').text(
                (typeof pron === "number") ? pron.toFixed(1) : '–'
            );

            // Detailed metric table
            $element.find('#pte-summary-pron').text(
                (typeof pron === "number") ? pron.toFixed(1) : '–'
            );
            $element.find('#pte-summary-accuracy').text(
                (typeof acc === "number") ? acc.toFixed(1) : '–'
            );
            $element.find('#pte-summary-fluency').text(
                (typeof flu === "number") ? flu.toFixed(1) : '–'
            );
            $element.find('#pte-summary-prosody').text(
                (typeof pro === "number") ? pro.toFixed(1) : '–'
            );
            $element.find('#pte-summary-completeness').text(
                (typeof comp === "number") ? comp.toFixed(1) : '–'
            );

            // Word-level feedback
            $wordsBody.empty();
            if (Array.isArray(fb.words)) {
                fb.words.forEach(function (w) {
                    var $row = $('<tr></tr>');
                    $('<td></td>').text(w.word || '').appendTo($row);
                    $('<td></td>').text(
                        (typeof w.accuracy === "number") ? w.accuracy : ''
                    ).appendTo($row);
                    $('<td></td>').text(w.error || '').appendTo($row);
                    $wordsBody.append($row);
                });
            }
        },
        error: function (xhr, status, errorThrown) {
            console.error("XHR error:", status, errorThrown);
            setStatus("Network/Server error while scoring your answer.");
        }
    });
}

// Bind events
$startBtn.on('click', startRecording);
$stopBtn.on('click', stopRecording);
}


function PTEXBlockStudio(runtime, element) {
    var $el = $(element);

    var $titleInput = $el.find('#pte-title');
    var $instrInput = $el.find('#pte-instructions');
    var $refInput   = $el.find('#pte-reference-text');
    var $apiInput   = $el.find('#pte-api-url');
    var $saveBtn    = $el.find('#pte-save-settings');
    var $status     = $el.find('#pte-save-status');

    function setStatus(msg) {
        $status.text(msg);
    }

    $saveBtn.on('click', function (e) {
        e.preventDefault();

        var handlerUrl = runtime.handlerUrl(element, 'save_studio_settings');

        var payload = {
            display_name:  $titleInput.val(),
            instructions:  $instrInput.val(),
            reference_text: $refInput.val(),
            api_url:       $apiInput.val()
        };

        $.ajax({
            type: "POST",
            url: handlerUrl,
            data: JSON.stringify(payload),
            contentType: "application/json",
            dataType: "json",
            success: function (resp) {
                if (resp && resp.status === "ok") {
                    setStatus("Settings saved.");
                } else {
                    setStatus("Error: " + (resp && resp.message ? resp.message : "Unknown error."));
                }
            },
            error: function () {
                setStatus("Network error while saving settings.");
            }
        });
    });
}
