<template>
  <div>
    <div class="toolbar">
      <AiButton v-permission="['ops', 'admin']" type="primary" @click="createVisible = true">
        新建版本
      </AiButton>
      <span class="hint">灰度发布 · 回滚需二次确认 · 全量发布需评测达标</span>
    </div>
    <el-empty v-if="!versions.length && !loading" description="暂无版本，先新建" />
    <el-table v-loading="loading" :data="versions" style="width: 100%">
      <el-table-column type="expand">
        <template #default="s">
          <div class="expand">
            <div class="expand-row">
              <span class="expand-label">正文</span>
              <pre class="expand-pre">{{ s.row.content }}</pre>
            </div>
            <div class="expand-row">
              <span class="expand-label">变量</span>
              <span v-if="s.row.variables.length">{{ s.row.variables.join('、') }}</span>
              <span v-else class="hint">无</span>
            </div>
            <div class="expand-row">
              <span class="expand-label">创建</span>
              <span>{{ s.row.created_by }} · {{ s.row.created_at }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="100" />
      <el-table-column prop="desc" label="说明" min-width="200" />
      <el-table-column label="灰度" width="120">
        <template #default="s">{{ s.row.gray }}%</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="s">
          <el-tag :type="versionTag(s.row.status)" size="small">
            {{ VERSION_TAG[s.row.status] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="s">
          <AiButton v-permission="['admin']" link @click="openPublish(s.row)">发布</AiButton>
          <AiButton
            v-permission="['admin']"
            link
            :disabled="s.row.status !== 'gray'"
            @click="adjustGray(s.row)"
          >
            调灰
          </AiButton>
          <AiButton
            v-permission="['admin']"
            link
            type="danger"
            @click="emit('rollback', s.row.version)"
          >
            回滚
          </AiButton>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      :current-page="page"
      :page-size="size"
      :page-sizes="[10, 20, 50, 100]"
      :total="total"
      layout="sizes, prev, pager, next, total"
      @size-change="emit('size-change', $event)"
      @current-change="emit('page-change', $event)"
    />

    <el-dialog v-model="createVisible" title="新建 Prompt 版本" width="560px">
      <AiInput v-model="createDesc" placeholder="版本说明（如：售后话术收敛）" maxlength="200" />
      <div style="height: 8px" />
      <AiInput
        v-model="createContent"
        type="textarea"
        :rows="8"
        placeholder="system prompt 全文，可用 {{变量名}} 声明变量"
      />
      <p class="hint">变量预览：{{ createVars.length ? createVars.join('、') : '无' }}</p>
      <template #footer>
        <AiButton @click="createVisible = false">取消</AiButton>
        <AiButton type="primary" @click="submitCreate">创建草稿</AiButton>
      </template>
    </el-dialog>

    <el-dialog v-model="publishVisible" title="发布版本" width="480px">
      <p>发布 {{ publishVersion }}（灰度比例）</p>
      <el-slider v-model="publishGray" :min="0" :max="100" show-input style="width: 100%" />
      <p class="hint">100%=全量上线（需最近评测达验收线）；其余进灰度，不拦评测。</p>
      <template #footer>
        <AiButton @click="publishVisible = false">取消</AiButton>
        <AiButton type="primary" @click="submitPublish">确认发布</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// Studio Prompt 版本窗格（版本列表+灰度+回滚+新建/发布对话框，对齐页面设计 §3.6）
// 纯展示 + 对话框本地态；数据变更一律上抛给 StudioView（唯一调用 composable 处）
import { computed, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { PromptVersion } from '@/types/agent';

type VersionStatus = keyof typeof VERSION_TAG;

defineProps<{
  versions: PromptVersion[];
  total: number;
  page: number;
  size: number;
  loading: boolean;
}>();

const emit = defineEmits([
  'page-change',
  'size-change',
  'create',
  'publish',
  'set-gray',
  'rollback',
]);

const VERSION_TAG = {
  online: '线上',
  gray: '灰度中',
  draft: '草稿',
  archived: '已归档',
} as const;

const createVisible = ref(false);
const createDesc = ref('');
const createContent = ref('');
const publishVisible = ref(false);
const publishVersion = ref('');
const publishGray = ref(100);

const versionTag = (s: VersionStatus) => {
  if (s === 'online') return 'success';
  if (s === 'gray') return 'warning';
  return 'info';
};

const createVars = computed(() => {
  const found = createContent.value.match(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g) ?? [];
  return [...new Set(found.map(s => s.replace(/[{}()\s]/g, '')))];
});

const submitCreate = () => {
  emit('create', { desc: createDesc.value.trim(), content: createContent.value });
  createVisible.value = false;
  createDesc.value = '';
  createContent.value = '';
};

const openPublish = (row: PromptVersion) => {
  publishVersion.value = row.version;
  publishGray.value = row.status === 'gray' ? row.gray : 100;
  publishVisible.value = true;
};

const submitPublish = () => {
  emit('publish', { version: publishVersion.value, gray: publishGray.value });
  publishVisible.value = false;
};

const adjustGray = async (row: PromptVersion) => {
  try {
    const { value } = await ElMessageBox.prompt('灰度比例 0-100（仅灰度中版本可调）', '调整灰度', {
      inputValue: String(row.gray),
      inputPattern: /^(100|[1-9]?\d)$/,
      inputErrorMessage: '请输入 0-100 的整数',
    });
    emit('set-gray', { version: row.version, gray: Number(value) });
  } catch {
    return;
  }
};
</script>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.hint {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.expand {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 8px;
}

.expand-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.expand-label {
  flex-shrink: 0;
  width: 48px;
  font-size: 12px;
  color: var(--reai-text-muted);
}

.expand-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
}
</style>
