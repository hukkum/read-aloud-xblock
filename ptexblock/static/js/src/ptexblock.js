function PTEXBlock(runtime, element) {
    var $root = $(element);

    // Buttons
    var $startBtn = $root.find('.pte-start');
    var $stopBtn = $root.find('.pte-stop');

    // Status / score (support both old IDs and new classes)
    var $status = $root.find('.pte-status-message, #pte-status');
    var $scoreSpan = $root.find('.pte-score-value, #pte-last-score');

    // Feedback container (can be hidden by default)
    var $feedbackBox = $root.find('.pte-feedback, #pte-feedback');
    var $wordsBody  = $root.find('.pte-words-table tbody, #pte-words-table tbody');

    // Summary cells (support both class and id patterns)
    var $summaryPron         = $root.find('.pte-summary-pron, #pte-summary-pron');
    var $summaryAccuracy     = $root.find('.pte-summary-accuracy, #pte-summary-accuracy');
    var $summaryFluency      = $root.find('.pte-summary-fluency, #pte-summary-fluency');
    var $summaryProsody      = $root.find('.pte-summary-prosody, #pte-summary-prosody');
    var $summaryCompleteness = $root.find('.pte-summary-completeness, #pte-summary-completeness');

    var mediaRecorder = null;
    var recordedChunks = [];
    var stream = null;

    function setStatus(text) {
        if ($status.length) {
            $status.text(text);
        }
    }

    function setLastScore(score) {
        if (!$scoreSpan.length) {
            return;
        }
        if (typeof score === "number") {
            $scoreSpan.text(score.toFixed(1));
        } else {
            $scoreSpan.text(score);
        }
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
                        var dataUrl = reader.result;  // "data:audio/webm;base64,AAAA..."
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
                setStatus("Unable to access microphone: " + (err && err.message ? err.message : err));
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
                    var msg = (response && response.message) ? response.message : "Unknown error";
                    setStatus("Error scoring your answer: " + msg);
                    return;
                }

                setStatus("Answer submitted and scored. You can retry to improve your score.");

                // Overall score (0–90) – from response.score
                var score = response.score || 0;
                setLastScore(score);

                // Detailed feedback from backend
                var fb = response.feedback || {};
                if ($feedbackBox.length) {
                    $feedbackBox.show();
                }

                // Overall metrics
                var pron = fb.pron_score;
                var acc  = fb.accuracy;
                var flu  = fb.fluency;
                var pro  = fb.prosody;
                var comp = fb.completeness;

                if ($summaryPron.length) {
                    $summaryPron.text(typeof pron === "number" ? pron.toFixed(1) : '–');
                }
                if ($summaryAccuracy.length) {
                    $summaryAccuracy.text(typeof acc === "number" ? acc.toFixed(1) : '–');
                }
                if ($summaryFluency.length) {
                    $summaryFluency.text(typeof flu === "number" ? flu.toFixed(1) : '–');
                }
                if ($summaryProsody.length) {
                    $summaryProsody.text(typeof pro === "number" ? pro.toFixed(1) : '–');
                }
                if ($summaryCompleteness.length) {
                    $summaryCompleteness.text(typeof comp === "number" ? comp.toFixed(1) : '–');
                }

                // Word-level details
                if ($wordsBody.length) {
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
