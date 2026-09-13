<template>
  <div class="voice-panel">
    <div v-if="recording" class="rec-row">
      <span class="rec-dot" />
      <span>录音中 {{ seconds }}s（≤60s，上滑取消暂不支持请点停止）</span>
      <AiButton @click="stopRec">停止</AiButton>
    </div>
    <div v-if="!recording && audioUrl" class="play-row">
      <canvas ref="waveRef" width="220" height="40" class="wave" />
      <audio :src="audioUrl" controls class="player" @play="muteOthers" />
    </div>
    <div v-if="!recording && audioUrl" class="row">
      <AiButton @click="toText">转文字</AiButton>
      <AiButton @click="discardAll">丢弃</AiButton>
    </div>
    <p v-if="voiceError" class="err">{{ voiceError }}</p>
    <div v-if="transcript" class="row">
      <AiInput v-model="editable" placeholder="转写结果，可改后填入" />
      <AiButton @click="confirmText">填入</AiButton>
    </div>
    <p v-if="transcript" class="muted">
      置信 {{ transcript.confidence.toFixed(2) }}{{ transcript.need_confirm ? '（偏低，请核对后发送）' : '' }}
    </p>
    <div class="row">
      <span class="muted">TTS</span>
      <el-switch v-model="ttsOn" size="small" />
      <el-select v-model="voice" size="small" class="voice-sel">
        <el-option v-for="v in voices" :key="v" :label="v" :value="v" />
      </el-select>
      <AiButton @click="speak">朗读</AiButton>
    </div>
  </div>
</template>

<script setup lang="ts">
// 语音面板（对齐 FR-1.3 + 页面设计 §3.1：波形 + 播放互斥 + 转写文字对照 + TTS 开关/音色）
// 录音经 useVoiceRecorder（≤60s）；转写调后端 ASR（低置信回问确认）；朗读走浏览器语音 + 后端音色口径。
import { ElMessage, ElOption, ElSelect, ElSwitch } from 'element-plus';
import { nextTick, onMounted, ref } from 'vue';
import { synthesizeApi, transcribeVoiceApi, ttsConfigApi } from '@/api';
import { useVoiceRecorder } from '@/composables/useVoiceRecorder';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';

const emits = defineEmits(['transcribed']);

const {
  recording,
  seconds,
  audioUrl,
  audioBlob,
  error: voiceError,
  start,
  stop,
  discard,
} = useVoiceRecorder();
const transcript = ref({ text: '', confidence: 0, need_confirm: false } as {
  text: string;
  confidence: number;
  need_confirm: boolean;
} | null);
const editable = ref('');
const ttsOn = ref(true);
const voices = ref<string[]>(['晓晓']);
const voice = ref('晓晓');
const waveRef = ref<HTMLCanvasElement | null>(null);
let lastBlob: Blob | null = null;

// 播放互斥：播 A 停 B（页面设计 §4）
const muteOthers = (e: Event) => {
  document.querySelectorAll('audio').forEach(a => {
    if (a !== e.target) {
      a.pause();
    }
  });
};

// 伪波形：由 blob 大小哈希定高，保证同段录音同波形（装饰性，不代表真实频谱）
const drawWave = () => {
  const canvas = waveRef.value;
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    return;
  }
  const seed = lastBlob?.size ?? 7;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#7c6cf0';
  for (let x = 0; x < canvas.width; x += 6) {
    const h = 6 + ((seed * (x + 3)) % 28);
    ctx.fillRect(x, (canvas.height - h) / 2, 3, h);
  }
};

const stopRec = () => {
  stop();
  nextTick(() => drawWave());
};

const startRec = () => {
  transcript.value = null;
  lastBlob = null;
  start();
};

const toText = async () => {
  const blob = audioBlob.value;
  if (!blob) {
    return;
  }
  try {
    lastBlob = blob;
    const data = await transcribeVoiceApi({
      file: new File([blob], 'voice.webm', { type: blob.type || 'audio/webm' }),
    });
    transcript.value = {
      text: data.text,
      confidence: data.confidence,
      need_confirm: data.need_confirm,
    };
    editable.value = data.text;
  } catch {
    ElMessage.error('转写失败，请重试');
  }
};

const confirmText = () => {
  if (!editable.value.trim()) {
    return;
  }
  emits('transcribed', { text: editable.value.trim() });
  discardAll();
};

const discardAll = () => {
  discard();
  transcript.value = null;
  editable.value = '';
  lastBlob = null;
};

const speak = async () => {
  if (!ttsOn.value) {
    ElMessage.info('TTS 已关闭，仅看文字对照');
    return;
  }
  const text = editable.value.trim() || transcript.value?.text || '';
  if (!text) {
    ElMessage.warning('暂无可朗读的文本');
    return;
  }
  try {
    await synthesizeApi({ text, voice: voice.value });
  } catch {
    ElMessage.error('合成失败，已用本地朗读降级');
  }
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'zh-CN';
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utter);
};

onMounted(async () => {
  try {
    const cfg = await ttsConfigApi();
    ttsOn.value = cfg.enabled !== false;
    if (Array.isArray(cfg.voices) && cfg.voices.length) {
      voices.value = cfg.voices;
    }
    voice.value = cfg.voice || voices.value[0];
  } catch {
    voice.value = voices.value[0];
  }
});

defineExpose({ startRec, stopRec, recording });
</script>

<style scoped>
.voice-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  color: var(--reai-text-main);
}

.rec-row,
.play-row,
.row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.rec-dot {
  width: 10px;
  height: 10px;
  background: var(--reai-notice);
  border-radius: 50%;
  animation: blink 1s infinite;
}

.wave {
  background: var(--reai-card-2);
  border-radius: 8px;
}

.player {
  max-width: 240px;
  height: 32px;
}

.voice-sel {
  width: 110px;
}

.err {
  margin: 0;
  font-size: 12px;
  color: var(--reai-notice);
}

.muted {
  margin: 0;
  font-size: 12px;
  color: var(--reai-text-muted);
}

@keyframes blink {
  50% {
    opacity: 0.3;
  }
}
</style>
