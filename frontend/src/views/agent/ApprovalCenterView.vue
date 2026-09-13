<template>
  <div class="page">
    <div class="head">
      <h2>审批中心</h2>
      <el-tag v-if="demo" type="warning" size="small">演示数据</el-tag>
    </div>
    <div class="filters">
      <el-select v-model="status" placeholder="状态" class="sel" @change="reload">
        <el-option
          v-for="o in STATUS_OPTIONS"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </el-select>
      <AiButton @click="reload">查询</AiButton>
    </div>
    <el-table v-loading="loading" :data="rows" class="table" @row-click="open">
      <el-table-column prop="action_label" label="动作" width="100" />
      <el-table-column prop="target" label="对象" />
      <el-table-column prop="applicant" label="申请人" width="100" />
      <el-table-column label="状态" width="100">
        <template #default="s">
          <el-tag :type="approvalTagOf(s.row.status)" size="small">{{ s.row.status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="170">
        <template #default="s">
          <el-button
            v-permission="['shop', 'ops', 'admin']"
            link
            type="primary"
            size="small"
            :disabled="s.row.status !== 'pending'"
            @click.stop="approve(s.row as ApprovalItem)"
          >
            批准
          </el-button>
          <el-button
            v-permission="['shop', 'ops', 'admin']"
            link
            type="danger"
            size="small"
            :disabled="s.row.status !== 'pending'"
            @click.stop="reject(s.row as ApprovalItem)"
          >
            驳回
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-drawer v-model="drawer" title="审批详情" size="420px">
      <div v-if="current" class="detail">
        <p class="kv">动作：{{ current.action_label }}（{{ current.action }}）</p>
        <p class="kv">对象：{{ current.target }}</p>
        <p class="kv">申请人：{{ current.applicant }}</p>
        <p class="kv">状态：{{ current.status_label }}</p>
        <p class="kv">申请原因：{{ current.reason || '-' }}</p>
        <p class="kv">参数：</p>
        <pre class="args">{{ prettyArgs }}</pre>
        <p v-if="current.approver" class="kv">审批人：{{ current.approver }}</p>
        <div v-if="current.status === 'pending'" class="ops">
          <AiButton v-permission="['shop', 'ops', 'admin']" @click="approve(current)">
            批准
          </AiButton>
          <AiButton v-permission="['shop', 'ops', 'admin']" @click="approveWithArgs(current)">
            改参批准
          </AiButton>
          <AiButton v-permission="['shop', 'ops', 'admin']" @click="reject(current)">
            驳回
          </AiButton>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
// 审批中心（列表 + 详情抽屉 + 批准/驳回/改参批准；批驳按钮仅店长/运营/管理员可见，对齐页面设计 §3.4）
import { ElDrawer, ElMessage, ElMessageBox, ElTable, ElTableColumn, ElTag, ElSelect, ElOption, ElButton } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { approveApprovalApi, listApprovalsApi, rejectApprovalApi } from '@/api';
import { mockApprovals } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import { approvalTagOf } from '@/types/approval';
import type { ApprovalItem } from '@/types/approval';

const STATUS_OPTIONS = [
  { value: 'pending', label: '待审批' },
  { value: '', label: '全部' },
];

const rows = ref<ApprovalItem[]>([]);
const status = ref('pending');
const loading = ref(false);
const demo = ref(false);
const drawer = ref(false);
const current = ref<ApprovalItem | null>(null);

const prettyArgs = computed(() => JSON.stringify(current.value?.args ?? {}, null, 2));

const load = async () => {
  loading.value = true;
  try {
    rows.value = await listApprovalsApi({ status: status.value });
    demo.value = false;
  } catch {
    rows.value = mockApprovals.filter((a) => !status.value || a.status === status.value);
    demo.value = true;
  } finally {
    loading.value = false;
  }
};

const reload = () => {
  load();
};

const open = (row: ApprovalItem) => {
  current.value = row;
  drawer.value = true;
};

const approve = async (row: ApprovalItem) => {
  try {
    await ElMessageBox.confirm(`批准「${row.action_label}｜${row.target}」并立即生效吗？`, '批准确认');
  } catch {
    return;
  }
  await decide(row, {}, '审批已通过并生效');
};

// 改参批准：审批人改金额/参数后再批（如 199 改成 209）
const approveWithArgs = async (row: ApprovalItem) => {
  let raw: string;
  try {
    ({ value: raw } = await ElMessageBox.prompt(
      '改后参数（JSON，可空则直接批准）',
      '改参批准',
      { inputValue: JSON.stringify(row.args) },
    ));
  } catch {
    return;
  }
  let modified: object = {};
  if (raw.trim()) {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (typeof parsed !== 'object' || parsed === null) {
        throw new Error('not object');
      }
      modified = parsed;
    } catch {
      ElMessage.warning('参数不是合法 JSON 对象');
      return;
    }
  }
  await decide(row, modified, '已按改后参数批准并生效');
};

const reject = async (row: ApprovalItem) => {
  let reason: string;
  try {
    ({ value: reason } = await ElMessageBox.prompt('驳回理由（必填，留痕）', '驳回'));
  } catch {
    return;
  }
  if (!reason.trim()) {
    ElMessage.warning('驳回理由必填');
    return;
  }
  try {
    await rejectApprovalApi({ id: row.id, reason: reason.trim() });
    ElMessage.success('已驳回，原数据保持不变');
    drawer.value = false;
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '驳回失败');
  }
};

const decide = async (row: ApprovalItem, modified: object, okMsg: string) => {
  try {
    await approveApprovalApi({ id: row.id, modifiedArgs: modified });
    ElMessage.success(okMsg);
    drawer.value = false;
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '批准失败');
  }
};

onMounted(() => {
  load();
});
</script>

<style scoped>
.page {
  padding: 16px;
}

.head {
  display: flex;
  gap: 12px;
  align-items: center;
}

.head h2 {
  margin: 0;
  font-size: 18px;
  color: var(--reai-text-main);
}

.filters {
  display: flex;
  gap: 8px;
  margin: 12px 0;
}

.sel {
  width: 140px;
}

.table {
  width: 100%;
  cursor: pointer;
}

.detail {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kv {
  margin: 4px 0;
  font-size: 14px;
  color: var(--reai-text-main);
}

.args {
  padding: 8px;
  font-size: 12px;
  color: var(--reai-text-main);
  background: var(--reai-card-2);
  border-radius: 8px;
  white-space: pre-wrap;
}

.ops {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
