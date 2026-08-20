/**
 * candidate_profile.js
 *
 * Adds an in-browser voice recording feature to the candidate profile
 * edit form (candidate_profile.html): "Record" starts capturing from the
 * microphone via the MediaRecorder API, "Stop recording" ends it, builds
 * an audio Blob, previews it in an <audio> element, and injects it into
 * the hidden file input so it's uploaded as part of the normal form
 * submission (as though the candidate had picked a file from disk).
 */

let media_recorder, media_stream, chunks = [], recording = false;
const record_btn = document.getElementById('record-btn');

record_btn.addEventListener('click', async () => {
    if (!recording) {
        // asks the browser for microphone access
        media_stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        media_recorder = new MediaRecorder(media_stream);
        chunks = [];

        media_recorder.ondataavailable = (e) => chunks.push(e.data);

        // combine all chunks into one audio file
        media_recorder.onstop = () => {
            // Release the microphone as soon as recording stops, rather
            // than holding onto it for the rest of the page's lifetime.
            media_stream.getTracks().forEach(track => track.stop());

            const blob = new Blob(chunks, { type: 'audio/webm' });
            const preview = document.getElementById('preview');
            preview.src = URL.createObjectURL(blob);
            preview.style.display = 'block';

            // A DataTransfer is the only way to programmatically set the
            // .files of a real <input type="file">, so the recorded clip
            // travels to the server exactly like a manually-picked file
            // when the form is submitted.
            const dt = new DataTransfer();
            dt.items.add(new File([blob], "voice.webm", { type: "audio/webm" }));
            document.getElementById('voice-file-input').files = dt.files;
        };

        media_recorder.start();
        recording = true;
        record_btn.textContent = "Stop recording";
        
    } 
    else {
        media_recorder.stop();
        recording = false;
        record_btn.textContent = "Record a voice introduction";
    }
});
