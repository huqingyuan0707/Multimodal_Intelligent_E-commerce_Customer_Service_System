<template>
  <div class="page">
    <div class="head">
      <el-tag v-if="demo" type="warning" size="small">演示数据</el-tag>
      <span class="sla">超时自动升级 · 记录不可篡改</span>
    </div>
    <div class="filters">
      <el-select v-model="status" placeholder="状态" class="sel" @change="onSearch">
        <el-option
          v-for="o in APPROVAL_STATUS_OPTIONS"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </el-select>
      <el-select v-model="action" placeholder="类型" class="sel" @change="onSearch">
        <el-option
          v-for="o in APPROVAL_ACTION_OPTIONS"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </el-select>
      <AiInput
        v-model="keyword"
        placeholder="搜对象/申请人/原因"
        class="kw"
        clearable
        @keyup.enter="onSearch"
      />
      <AiButton @click="onSearch">查询</AiButton>
      <el-checkbox v-model="overdueOnly" @change="onSearch">只看超期</el-checkbox>
      <AiButton v-permission="['shop', 'ops', 'admin']" @click="batch">批量批准</AiButton>
    </div>
    <el-table
      v-loading="loading"
      :data="rows"
      class="table"
      empty-text="暂无审批单"
      @row-click="open"
      @selection-change="onSelection"
    >
      <el-table-column type="selection" width="44" />
      <el-table-column prop="action_label" label="动作" width="110" />
      <el-table-column prop="target" label="对象" min-width="160" />
      <el-table-column label="金额" width="150">
        <template #default="s">{{ approvalAmountOf(s.row as ApprovalItem) || '-' }}</template>
      </el-table-column>
      <el-table-column prop="applicant" label="申请人" width="100" />
      <el-table-column label="状态" width="130">
        <template #default="s">
          <el-tag :type="approvalTagOf((s.row as ApprovalItem).status)" size="small">
            {{ (s.row as ApprovalItem).status_label }}
          </el-tag>
          <el-tag v-if="(s.row as ApprovalItem).overdue" type="danger" size="small"> 超期 </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="等待" width="130">
        <template #default="s">{{ approvalWaitingOf(s.row as ApprovalItem) }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="s">
          <AiButton
            v-permission="['shop', 'ops', 'admin']"
            link
            type="primary"
            size="small"
            :disabled="s.row.status !== 'pending'"
            @click.stop="approveOne(s.row as ApprovalItem)"
          >
            批准
          </AiButton>
          <AiButton
            v-permission="['shop', 'ops', 'admin']"
            link
            type="danger"
            size="small"
            :disabled="s.row.status !== 'pending'"
            @click.stop="rejectOne(s.row as ApprovalItem)"
          >
            驳回
          </AiButton>
        </template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <el-pagination
        :current-page="page"
        :page-size="size"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        layout="sizes, prev, pager, next, total"
        @current-change="onPage"
        @size-change="onSize"
      />
    </div>
    <el-drawer v-model="drawer" title="审批详情" size="440px">
      <div v-if="current" class="detail">
        <p class="kv">动作：{{ current.action_label }}（{{ current.action }}）</p>
        <p class="kv">对象：{{ current.target }}</p>
        <p class="kv">金额：{{ approvalAmountOf(current) || '-' }}</p>
        <p class="kv">申请人：{{ current.applicant }}</p>
        <p class="kv">状态：{{ current.status_label }} · {{ approvalWaitingOf(current) }}</p>
        <p class="kv">申请原因：{{ current.reason || '-' }}</p>
        <p class="kv">参数：</p>
        <pre class="args">{{ prettyArgs }}</pre>
        <div v-if="approvalEvidenceOf(current).length" class="ev">
          <p class="kv">证据图：</p>
          <el-image
            v-for="u in approvalEvidenceOf(current)"
            :key="u"
            :src="u"
            class="thumb"
            preview-teleported
          />
        </div>
        <p v-if="current.session_id" class="kv">关联会话：{{ current.session_id }}</p>
        <p v-if="current.approver" class="kv">
          审批人：{{ current.approver }}{{ current.decided_at ? ` · ${current.decided_at}` : '' }}
        </p>
        <p v-if="current.overdue" class="kv">
          <el-tag type="danger" size="small"
            >已超期 {{ current.waiting_hours }} 小时，请优先处理</el-tag
          >
        </p>
        <div v-if="policyRefs.length" class="ev">
          <p class="kv">政策引用：</p>
          <AiButton
            v-for="p in policyRefs"
            :key="p.id"
            link
            type="primary"
            size="small"
            @click="goPolicy(p.title)"
          >
            《{{ p.title }}》
          </AiButton>
        </div>
        <div v-if="current.status === 'pending'" class="ops">
          <AiButton v-permission="['shop', 'ops', 'admin']" @click="approveOne(current)">
            批准
          </AiButton>
          <AiButton v-permission="['shop', 'ops', 'admin']" @click="approveWithArgs(current)">
            改参批准
          </AiButton>
          <AiButton v-permission="['shop', 'ops', 'admin']" @click="rejectOne(current)">
            驳回
          </AiButton>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
// 审批中心（服务端分页 + 状态/类型/关键字/超期筛选 + 批量批 + 证据图/政策引用/超时透出；确认与幂等下沉 useApproval，对齐页面设计 §3.4）
import {
  ElCheckbox,
  ElDrawer,
  ElImage,
  ElMessage,
  ElPagination,
  ElTable,
  ElTableColumn,
  ElTag,
  ElSelect,
  ElOption,
} from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { getApprovalDetailApi, listApprovalsApi } from '@/api';
import { useApproval } from '@/composables/useApproval';
import { mockApprovals } from '@/mock';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import {
  APPROVAL_ACTION_OPTIONS,
  APPROVAL_STATUS_OPTIONS,
  approvalAmountOf,
  approvalEvidenceOf,
  approvalTagOf,
  approvalWaitingOf,
} from '@/types/approval';
import type { ApprovalItem, ApprovalPolicyRef } from '@/types/approval';

const router = useRouter();
const rows = ref<ApprovalItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const status = ref('pending');
const action = ref('');
const keyword = ref('');
const overdueOnly = ref(false);
const loading = ref(false);
const demo = ref(false);
const drawer = ref(false);
const current = ref<ApprovalItem | null>(null);
// 政策引用：抽屉打开时调详情接口拿，点击跳知识库按标题筛选；失败回空不断渲染
const policyRefs = ref<ApprovalPolicyRef[]>([]);
const selected = ref<ApprovalItem[]>([]);

const prettyArgs = computed(() => JSON.stringify(current.value?.args ?? {}, null, 2));

const load = async () => {
  loading.value = true;
  try {
    const data = await listApprovalsApi({
      status: status.value,
      action: action.value,
      keyword: keyword.value.trim(),
      overdue: overdueOnly.value,
      page: page.value,
      size: size.value,
    });
    rows.value = data.items;
    total.value = data.total;
    demo.value = false;
  } catch {
    const kw = keyword.value.trim();
    const filtered = mockApprovals.filter(
      a =>
        (!status.value || a.status === status.value) &&
        (!action.value || a.action === action.value) &&
        (!kw || `${a.target}${a.applicant}${a.reason}`.includes(kw)),
    );
    total.value = filtered.length;
    rows.value = filtered.slice((page.value - 1) * size.value, page.value * size.value);
    demo.value = true;
    ElMessage.warning('后端不可用，已显示演示数据');
  } finally {
    loading.value = false;
  }
};

const reload = () => {
  drawer.value = false;
  load();
};

const { approveOne, approveWithArgs, rejectOne, approveBatch } = useApproval(reload);

const onSearch = () => {
  page.value = 1;
  load();
};

const onPage = (p: number) => {
  page.value = p;
  load();
};

const onSize = (s: number) => {
  size.value = s;
  page.value = 1;
  load();
};

const onSelection = (vals: ApprovalItem[]) => {
  selected.value = vals;
};

const open = async (row: ApprovalItem) => {
  current.value = row;
  drawer.value = true;
  policyRefs.value = [];
  // 详情接口带超期标记 + 政策引用；演示模式/失败时回退行数据不断抽屉
  try {
    const detail = await getApprovalDetailApi(row.id);
    policyRefs.value = Array.isArray(detail?.policy_refs) ? detail.policy_refs : [];
    if (detail && typeof detail === 'object') {
      current.value = { ...row, ...(detail as object) };
    }
  } catch {
    policyRefs.value = [];
  }
};

const goPolicy = (title: string) => {
  router.push({ path: '/knowledge', query: { keyword: title } });
};

const batch = () => {
  approveBatch(selected.value);
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

.sla {
  font-size: 12px;
  color: var(--reai-text-muted);
}

.filters {
  display: flex;
  gap: 8px;
  margin: 12px 0;
}

.sel {
  width: 130px;
}

.kw {
  width: 220px;
}

.table {
  width: 100%;
  cursor: pointer;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
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

.ev {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.thumb {
  width: 72px;
  height: 72px;
  border-radius: 8px;
}

.ops {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
