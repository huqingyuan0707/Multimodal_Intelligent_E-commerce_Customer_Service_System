<template>
  <div class="page">
    <div class="head">
      <el-tag type="info" size="small">演示数据（后端接口待接）</el-tag>
    </div>
    <el-tabs v-model="tab">
      <el-tab-pane label="Prompt" name="prompt">
        <div class="toolbar">
          <AiButton v-permission="['ops', 'admin']" type="primary" @click="openCreate">
            新建版本
          </AiButton>
          <span class="hint">灰度发布 · 回滚需二次确认</span>
        </div>
        <el-empty v-if="!versions.length && !loading" description="暂无版本，先新建" />
        <el-table v-loading="loading" :data="versions" style="width: 100%">
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
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="s">
              <AiButton v-permission="['admin']" link @click="publishVersion(s.row)">
                发布
              </AiButton>
              <AiButton v-permission="['admin']" link type="danger" @click="rollbackVersion(s.row)">
                回滚
              </AiButton>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="sizes, prev, pager, next, total"
          @size-change="loadVersions"
          @current-change="loadVersions"
        />
      </el-tab-pane>
      <el-tab-pane label="工具" name="tool">
        <p class="hint">JSON Schema / Scope / 幂等 / 超时只读展示，试调走沙箱不写真实订单</p>
        <el-table v-loading="loading" :data="tools" style="width: 100%">
          <el-table-column prop="name" label="工具" min-width="160" />
          <el-table-column prop="scope" label="Scope" width="140" />
          <el-table-column prop="timeout" label="超时" width="100" />
          <el-table-column label="幂等" width="90">
            <template #default="s">{{ s.row.idempotent ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="s">
              <AiButton v-permission="['ops', 'admin']" link @click="trialTool(s.row)">
                试调
              </AiButton>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="评测" name="eval">
        <div class="toolbar">
          <AiInput v-model="goldSet" placeholder="黄金集（如 default-200）" clearable />
          <AiButton
            v-permission="['ops', 'admin']"
            type="primary"
            :loading="running"
            @click="runEval"
          >
            一键跑
          </AiButton>
        </div>
        <el-alert
          v-if="!pass"
          type="error"
          show-icon
          title="不达标禁发布：faithfulness 低于 0.95 或拦截率异常时禁止发布新版本"
        />
        <el-descriptions :column="3" border>
          <el-descriptions-item label="faithfulness">{{ result.faith }}</el-descriptions-item>
          <el-descriptions-item label="拦截率">{{ result.guard }}</el-descriptions-item>
          <el-descriptions-item label="结论">{{ pass ? '达标可发布' : '不达标禁发布' }}</el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
// Studio 三窗格：Prompt版本灰度回滚 + 工具只读试调 + 评测跑分禁发布红条
// 对齐页面设计 §3.6、design.pen Agent工作室-/studio，后端接口待接先用本地演示数据
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';

const VERSION_TAG = {
  online: '线上',
  gray: '灰度中',
  draft: '草稿',
} as const;

type VersionStatus = keyof typeof VERSION_TAG;

type PromptVersion = {
  version: string;
  desc: string;
  gray: number;
  status: VersionStatus;
};

type ToolItem = {
  name: string;
  scope: string;
  timeout: string;
  idempotent: boolean;
};

const tab = ref('prompt');
const loading = ref(false);
const running = ref(false);
const versions = ref<PromptVersion[]>([]);
const tools = ref<ToolItem[]>([]);
const page = ref(1);
const size = ref(20);
const total = ref(0);
const goldSet = ref('default-200');
const result = ref({ faith: '0.96', guard: '3%' });
const pass = ref(true);

const versionTag = (s: VersionStatus) => {
  if (s === 'online') return 'success';
  if (s === 'gray') return 'warning';
  return 'info';
};

const loadVersions = async () => {
  loading.value = true;
  try {
    const all: PromptVersion[] = [
      { version: 'v12', desc: '线上稳定版 · 售后话术收敛', gray: 100, status: 'online' },
      { version: 'v13', desc: '待发布 · 引用角标样式调整', gray: 50, status: 'gray' },
      { version: 'v14', desc: '草稿 · 多模态转人工阈值', gray: 0, status: 'draft' },
    ];
    total.value = all.length;
    versions.value = all;
    tools.value = [
      { name: 'order.query', scope: 'cs', timeout: '30s', idempotent: true },
      { name: 'stock.query', scope: 'cs', timeout: '30s', idempotent: true },
      { name: 'coupon.query', scope: 'shop', timeout: '30s', idempotent: true },
    ];
  } catch {
    versions.value = [];
    ElMessage.error('加载失败，请重试');
  } finally {
    loading.value = false;
  }
};

const openCreate = () => {
  ElMessage.success('演示环境：新建版本后请在评测达标后再发布');
};

const publishVersion = async (row: PromptVersion) => {
  if (!pass.value) {
    ElMessage.error('评测不达标，禁止发布');
    return;
  }
  await ElMessageBox.confirm(`确认发布 ${row.version} 全量线上吗？`, '提示');
  ElMessage.success(`${row.version} 已发布（演示）`);
};

const rollbackVersion = async (row: PromptVersion) => {
  await ElMessageBox.confirm(`确认回滚到 ${row.version} 吗？线上版本将被替换`, '提示');
  ElMessage.success(`已回滚到 ${row.version}（演示）`);
};

const trialTool = (row: ToolItem) => {
  ElMessage.success(`沙箱试调 ${row.name} 成功（演示，不写真实订单）`);
};

const runEval = async () => {
  if (!goldSet.value) {
    ElMessage.warning('请先填写黄金集');
    return;
  }
  running.value = true;
  try {
    result.value = { faith: '0.96', guard: '3%' };
    pass.value = true;
    ElMessage.success('评测完成：达标可发布（演示）');
  } finally {
    running.value = false;
  }
};

onMounted(() => {
  loadVersions();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
}

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
</style>
