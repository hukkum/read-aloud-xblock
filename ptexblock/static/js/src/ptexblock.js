function PTEXBlock(runtime, element, data) {
    'use strict';

    var $element     = $(element);

    // Buttons & core UI
    var $startBtn    = $element.find('.pte-start');
    var $stopBtn     = $element.find('.pte-stop');
    var $status      = $element.find('#pte-status');
    var $lastScore   = $element.find('#pte-last-score');
    var $feedbackBox = $element.find('#pte-feedback');
    var $wordsBody   = $element.find('#pte-words-table tbody');

    // Progress bar
    var $progressBar      = $element.find('.pte-progress-bar');
    var $progressInner    = $element.find('.pte-progress-bar-inner');

        // ----- Config: primary source is JS data from initialize_js -----
    // data = { mode, question_type, preroll_delay, recording_limit, max_attempts }

    var mode = (data && data.mode ? data.mode : 'practice').toString().toLowerCase();

    var preroll = parseInt(data && data.preroll_delay, 10);
    var recordingLimit = parseInt(data && data.recording_limit, 10);
    var maxAttempts = parseInt(data && data.max_attempts, 10);

    // Fallback to HTML attributes only if JS data is missing
    if (isNaN(preroll)) {
        preroll = parseInt($element.attr('data-preroll') || '0', 10);
    }
    if (isNaN(recordingLimit)) {
        recordingLimit = parseInt($element.attr('data-recording-limit') || '40', 10);
    }
    if (isNaN(maxAttempts)) {
        maxAttempts = parseInt(
            $element.attr('data-max-attempts') ||
            (mode === 'exam' ? '1' : '3'),
            10
        );
    }

    if (isNaN(preroll) || preroll < 0) {
        preroll = 0;
    }
    if (isNaN(recordingLimit) || recordingLimit <= 0) {
        recordingLimit = 40;
    }
    if (isNaN(maxAttempts) || maxAttempts <= 0) {
        maxAttempts = (mode === 'exam') ? 1 : 3;
    }

    console.log('PTE config (from JS data)',
        'mode:', mode,
        'preroll:', preroll,
        'recordingLimit:', recordingLimit,
        'maxAttempts:', maxAttempts
    );



    // State
    var mediaRecorder = null;
    var recordedChunks = [];
    var stream = null;

    var prepInterval = null;
    var mainInterval = null;
    var isPrepping = false;
    var attempts = 0;

    // Progress bookkeeping
    var totalDuration = Math.max(1, preroll + recordingLimit); // seconds
    var elapsed = 0;

    function setStatus(text) {
        // Status message only (label "Current Status:" is in HTML)
        $status.html(text);
    }

    function resetRecording() {
        recordedChunks = [];
    }

    function supportsMedia() {
        return !!(navigator.mediaDevices &&
                  navigator.mediaDevices.getUserMedia &&
                  window.MediaRecorder);
    }

    // --- Progress helpers ----------------------------------------------------

    function recalcTotalDuration() {
        totalDuration = Math.max(1, preroll + recordingLimit);
    }

    function setProgress(percent) {
        if (!$progressInner.length) {
            return;
        }
        if (percent < 0) { percent = 0; }
        if (percent > 100) { percent = 100; }
        $progressInner.css('width', percent + '%');
    }

    function setProgressRunning(running) {
        if (!$progressBar.length) {
            return;
        }
        if (running) {
            $progressBar.addClass('pte-progress-running');
        } else {
            $progressBar.removeClass('pte-progress-running');
        }
    }

    function startProgress() {
        recalcTotalDuration();
        elapsed = 0;
        setProgress(0);
        setProgressRunning(true);
    }

    function incrementProgress() {
        if (!totalDuration) {
            return;
        }
        elapsed += 1;
        if (elapsed > totalDuration) {
            elapsed = totalDuration;
        }
        var pct = (elapsed / totalDuration) * 100;
        setProgress(pct);
    }

    function finishProgress() {
        setProgressRunning(false);
        setProgress(100);
    }

    // --- Timer helpers -------------------------------------------------------

    function clearPrepTimer() {
        if (prepInterval) {
            window.clearInterval(prepInterval);
            prepInterval = null;
        }
    }

    function clearMainTimer() {
        if (mainInterval) {
            window.clearInterval(mainInterval);
            mainInterval = null;
        }
    }

    // --- Recording logic -----------------------------------------------------

    /**
     * Actual media recording start (called after prep countdown).
     */
    function startRecording() {
        if (mediaRecorder && mediaRecorder.state === "recording") {
            return;
        }

        if (!supportsMedia()) {
            setStatus("Recording is not supported in this browser.");
            finishProgress();
            return;
        }

        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(function (s) {
                stream = s;

                try {
                    mediaRecorder = new MediaRecorder(stream);
                } catch (e) {
                    console.error("MediaRecorder init error:", e);
                    setStatus("Unable to start recording: " + e.message);
                    if (stream) {
                        stream.getTracks().forEach(function (t) { t.stop(); });
                        stream = null;
                    }
                    finishProgress();
                    return;
                }

                resetRecording();

                mediaRecorder.ondataavailable = function (e) {
                    if (e.data && e.data.size > 0) {
                        recordedChunks.push(e.data);
                    }
                };

                mediaRecorder.onstop = function () {
                    clearMainTimer();

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
                setStatus("Recording...");

                // Start main timer when recording actually starts
                clearMainTimer();
                var remaining = recordingLimit;
                mainInterval = window.setInterval(function () {
                    remaining -= 1;
                    incrementProgress();

                    if (remaining <= 0) {
                        clearMainTimer();
                        stopRecordingInternal('auto');
                    }
                }, 1000);
            })
            .catch(function (err) {
                console.error("getUserMedia error:", err);
                setStatus("Unable to access microphone: " + (err && err.message ? err.message : err));
                finishProgress();
            });
    }

    /**
     * Shared stop logic (source = 'user' | 'auto')
     */
    function stopRecordingInternal(source) {
        clearPrepTimer();

        if (mediaRecorder && mediaRecorder.state === "recording") {
            mediaRecorder.stop();
        }

        $startBtn.prop('disabled', false);
        $stopBtn.prop('disabled', true);

        if (source === 'auto') {
            setStatus("Time is up. Uploading & scoring your answer...");
        } else {
            setStatus("Uploading & scoring your answer...");
        }

        finishProgress();
    }

    function stopRecording() {
        // User-triggered stop
        stopRecordingInternal('user');
    }

    /**
     * Start button click handler:
     *  - Checks attempts
     *  - Runs prep countdown if configured
     *  - Then calls startRecording()
     */
    function handleStartClick() {
        if (isPrepping) {
            return;
        }

        if (mode === 'practice' && maxAttempts > 0 && attempts >= maxAttempts) {
            setStatus("You’ve used all available attempts for this question.");
            $startBtn.prop('disabled', true);
            $stopBtn.prop('disabled', true);
            return;
        }

        if (mode === 'exam' && attempts >= 1) {
            setStatus("You have already submitted your response for this exam question.");
            $startBtn.prop('disabled', true);
            $stopBtn.prop('disabled', true);
            return;
        }

        // Start unified progress bar for prep + recording
        startProgress();

        // If no prep delay, start recording immediately
        if (!preroll || preroll <= 0) {
            setStatus("Recording...");
            startRecording();
            return;
        }

        // Prep countdown (like PTE "Beginning in XX seconds")
        isPrepping = true;
        $startBtn.prop('disabled', true);
        $stopBtn.prop('disabled', true);

        var remaining = preroll;
        setStatus("Beginning in " + remaining + " seconds...");

        clearPrepTimer();
        prepInterval = window.setInterval(function () {
            remaining -= 1;
            incrementProgress();

            if (remaining <= 0) {
                clearPrepTimer();
                isPrepping = false;
                setStatus("Recording...");
                startRecording();
                return;
            }

            setStatus("Beginning in " + remaining + " seconds...");
        }, 1000);
    }

    // --- Backend call --------------------------------------------------------

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

                attempts += 1;

                if (mode === 'exam') {
                    // Exam mode: do NOT show detailed feedback.
                    setStatus("Your response has been submitted.");
                    $startBtn.prop('disabled', true);
                    $stopBtn.prop('disabled', true);
                    return;
                }

                // Practice mode: show score & feedback
                setStatus(
                    "Answer submitted and scored. You can retry to improve your score "
                    + "(Attempt " + attempts + " of " + maxAttempts + ")."
                );

                var score = response.score || 0;
                if (typeof score === "number") {
                    $lastScore.text(score.toFixed(1));
                } else {
                    $lastScore.text(score);
                }

                var fb = response.feedback || {};

                // Show feedback panel (if allowed)
                if ($feedbackBox.length) {
                    $feedbackBox.show();
                }

                var pron = fb.pron_score;
                var acc  = fb.accuracy;
                var flu  = fb.fluency;
                var pro  = fb.prosody;
                var comp = fb.completeness;

                // Content heuristic: average of accuracy and completeness
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

                // If attempts exhausted in practice, lock further tries
                if (maxAttempts > 0 && attempts >= maxAttempts) {
                    $startBtn.prop('disabled', true);
                    $stopBtn.prop('disabled', true);
                    setStatus("Answer submitted and scored. You’ve reached the maximum number of attempts.");
                }
            },
            error: function (xhr, status, errorThrown) {
                console.error("XHR error:", status, errorThrown);
                setStatus("Network/Server error while scoring your answer.");
            }
        });
    }

    // --- Initial UI setup ----------------------------------------------------

    // In exam mode, hide feedback panel & last score UI at start
    if (mode === 'exam') {
        if ($feedbackBox.length) {
            $feedbackBox.hide();
        }
        $element.find('.pte-last-score-card').hide();
    }

    // Reset progress and status at load
    recalcTotalDuration();
    setProgress(0);
    setProgressRunning(false);
    setStatus('Click <strong>“Start”</strong> to begin. You will see a countdown before recording starts.');

    // Bind events
    $startBtn.on('click', handleStartClick);
    $stopBtn.on('click', stopRecording);
}
