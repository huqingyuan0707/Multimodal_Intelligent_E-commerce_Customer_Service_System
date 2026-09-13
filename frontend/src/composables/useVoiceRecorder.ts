// 语音录制最小闭环（MediaRecorder ≤60s + 计时 + 播放；ASR 转写/TTS 待后端接口，对齐 FR-1.3）
import { ref } from 'vue';

export const useVoiceRecorder = () => {
  const recording = ref(false);
  const seconds = ref(0);
  const audioUrl = ref('');
  const audioBlob = ref<Blob | null>(null);
  const error = ref('');
  const supported = typeof MediaRecorder !== 'undefined';
  let stream: MediaStream | null = null;
  let recorder: MediaRecorder | null = null;
  let timer: number | null = null;
  let chunks: Blob[] = [];

  const stopTracks = () => {
    stream?.getTracks().forEach(t => t.stop());
    stream = null;
  };

  const start = async () => {
    error.value = '';
    if (!supported) {
      error.value = '浏览器不支持录音';
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      error.value = '麦克风被拒绝或不可用';
      return;
    }
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data.size) {
        chunks.push(e.data);
      }
    };
    recorder.onstop = () => {
      if (audioUrl.value) {
        URL.revokeObjectURL(audioUrl.value);
      }
      audioBlob.value = new Blob(chunks, { type: recorder?.mimeType || 'audio/webm' });
      audioUrl.value = URL.createObjectURL(audioBlob.value);
      stopTracks();
    };
    recorder.start();
    recording.value = true;
    seconds.value = 0;
    timer = window.setInterval(() => {
      seconds.value += 1;
      if (seconds.value >= 60) {
        stop();
      }
    }, 1000);
  };

  const stop = async () => {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
    recording.value = false;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
    } else {
      stopTracks();
    }
  };

  const discard = () => {
    if (audioUrl.value) {
      URL.revokeObjectURL(audioUrl.value);
    }
    audioUrl.value = '';
    audioBlob.value = null;
    seconds.value = 0;
  };

  return { recording, seconds, audioUrl, audioBlob, error, supported, start, stop, discard };
};
