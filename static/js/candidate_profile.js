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
            media_stream.getTracks().forEach(track => track.stop());

            const blob = new Blob(chunks, { type: 'audio/webm' });
            const preview = document.getElementById('preview');
            preview.src = URL.createObjectURL(blob);
            preview.style.display = 'block';

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