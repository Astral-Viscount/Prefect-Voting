let mediaRecorder, chunks = [], recording = false;
const recordBtn = document.getElementById('recordBtn');

recordBtn.addEventListener('click', async () => {
    if (!recording) {
        // asks the browser for microphone access
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        chunks = [];

        mediaRecorder.ondataavailable = (e) => chunks.push(e.data);

        // combine all chunks into one audio file
        mediaRecorder.onstop = () => {
            const blob = new Blob(chunks, { type: 'audio/webm' });
            const preview = document.getElementById('preview');
            preview.src = URL.createObjectURL(blob);
            preview.style.display = 'block';

            const dt = new DataTransfer();
            dt.items.add(new File([blob], "voice.webm", { type: "audio/webm" }));
            document.getElementById('voiceFileInput').files = dt.files;
        };

        mediaRecorder.start();
        recording = true;
        recordBtn.textContent = "Stop recording";
        
    } 
    else {
        mediaRecorder.stop();
        recording = false;
        recordBtn.textContent = "Record a voice introduction";
    }
});