<template>
  <div>
    <div class="toolbar">
      <AiInput v-model="tenant" placeholder="租户编码（空=全部）" class="kw" />
      <el-select v-model="channel" placeholder="渠道" clearable class="kw-sm">
        <el-option v-for="c in CHANNEL_OPTIONS" :key="c.value" :label="c.label" :value="c.value" />
      </el-select>
      <el-select v-model="status" placeholder="状态" clearable class="kw-sm">
        <el-option label="草稿" value="draft" />
        <el-option label="启用" value="active" />
        <el-option label="已停用" value="disabled" />
      </el-select>
      <AiButton @click="reload">查询</AiButton>
      <AiButton v-permission="['admin']" type="primary" @click="openCreate">新建模板</AiButton>
    </div>

    <!-- 到达率：渠道网关未接入时如实显示未送达，不粉饰 -->
    <div class="reach">
      <span class="reach-item"
        >累计发送 <b>{{ reach.total_sent }}</b></span
      >
      <span class="reach-item"
        >未送达 <b>{{ reach.total_failed }}</b></span
      >
      <span class="reach-item">
        到达率 <b>{{ reach.no_data ? '—' : formatRate(reach.reach_rate) }}</b>
      </span>
      <span class="reach-note">{{ reach.window_note }}</span>
    </div>
    <el-alert
      v-if="reach.gateway_note"
      :title="reach.gateway_note"
      type="warning"
      :closable="false"
      show-icon
    />

    <el-table v-loading="loading" :data="rows" style="width: 100%">
      <el-table-column prop="name" label="模板名" min-width="140" />
      <el-table-column label="渠道" width="90">
        <template #default="s">{{ s.row.channel_label }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="s">
          <el-tag :type="templateStatusTagOf(s.row.status)" size="small">{{
            s.row.status_label
          }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="正文" min-width="220" show-overflow-tooltip>
        <template #default="s">{{ s.row.content }}</template>
      </el-table-column>
      <el-table-column label="发送/未送达" min-width="120">
        <template #default="s">{{ s.row.sent }} / {{ s.row.failed }}</template>
      </el-table-column>
      <el-table-column label="到达率" width="100">
        <template #default="s">
          <span v-if="s.row.no_data" class="muted">—</span>
          <span v-else>{{ formatRate(s.row.reach_rate) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="190">
        <template #default="s">
          <AiButton v-permission="['admin']" link @click="openEdit(s.row)">编辑</AiButton>
          <AiButton v-permission="['admin']" link @click="openSend(s.row)">测试发送</AiButton>
          <AiButton v-permission="['admin']" link @click="toggle(s.row)">
            {{ s.row.status === 'active' ? '停用' : '启用' }}
          </AiButton>
          <AiButton v-permission="['admin']" link @click="remove(s.row)">删除</AiButton>
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

    <el-dialog v-model="dialog" :title="form.id ? '编辑模板' : '新建模板'" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="租户"><AiInput v-model="form.tenant" /></el-form-item>
        <el-form-item label="模板名"><AiInput v-model="form.name" /></el-form-item>
        <el-form-item label="渠道">
          <el-select v-model="form.channel" class="kw-full">
            <el-option
              v-for="c in CHANNEL_OPTIONS"
              :key="c.value"
              :label="c.label"
              :value="c.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="正文">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="4"
            placeholder="可用 {user_ref} 占位，发送时替换为接收方"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" class="kw-full">
            <el-option label="草稿" value="draft" />
            <el-option label="启用（可发送）" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="dialog = false">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submit">保存</AiButton>
      </template>
    </el-dialog>

    <el-dialog v-model="sendDialog" title="测试发送" width="460px">
      <el-form :model="sendForm" label-width="90px">
        <el-form-item label="模板">{{ sendForm.name }}</el-form-item>
        <el-form-item label="接收方"
          ><AiInput v-model="sendForm.user_ref" placeholder="user_ref"
        /></el-form-item>
      </el-form>
      <p class="hint">受频控约束（同一接收方 24h 内默认 1 条）；网关未接入时会计为未送达。</p>
      <template #footer>
        <AiButton @click="sendDialog = false">取消</AiButton>
        <AiButton type="primary" :loading="sending" @click="submitSend">发送</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 消息模板窗格（FR-12.2 + 页面设计 §3.19）：模板 CRUD + 测试发送 + 累计到达率。
// 诚实口径：发送结果 delivered=false 时提示「未送达」而不是「已发送」——渠道网关未接入是现状。
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import {
  createTemplateApi,
  deleteTemplateApi,
  getReachApi,
  listTemplatesApi,
  sendNotifyApi,
  setTemplateStatusApi,
  updateTemplateApi,
} from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { CHANNEL_OPTIONS, formatRate, templateStatusTagOf } from '@/types/admin';
import type { MessageTemplateItem, ReachReport } from '@/types/admin';

const rows = ref<MessageTemplateItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const tenant = ref('');
const channel = ref('');
const status = ref('');
const loading = ref(false);
const submitting = ref(false);
const sending = ref(false);
const dialog = ref(false);
const sendDialog = ref(false);
const reach = ref<ReachReport>({
  items: [],
  total_sent: 0,
  total_failed: 0,
  total_delivered: 0,
  reach_rate: null,
  no_data: true,
  window_note: '',
  gateway_note: '',
});
const form = ref({
  id: '',
  tenant: '',
  name: '',
  channel: 'sms',
  content: '',
  status: 'draft',
});
const sendForm = ref({ tenant: '', name: '', user_ref: '' });

const loadReach = async () => {
  try {
    reach.value = await getReachApi({ tenant: tenant.value.trim() });
  } catch {
    reach.value = { ...reach.value, gateway_note: '' };
  }
};

const load = async () => {
  loading.value = true;
  try {
    const res = await listTemplatesApi({
      tenant: tenant.value.trim(),
      channel: channel.value,
      status: status.value,
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
    if (res.window_note) {
      reach.value = { ...reach.value, window_note: res.window_note };
    }
  } catch (e) {
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? e.message : '加载模板失败');
  } finally {
    loading.value = false;
  }
};

const reload = () => {
  page.value = 1;
  load();
  loadReach();
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

const openCreate = () => {
  form.value = {
    id: '',
    tenant: tenant.value.trim(),
    name: '',
    channel: 'sms',
    content: '',
    status: 'draft',
  };
  dialog.value = true;
};

const openEdit = (row: MessageTemplateItem) => {
  form.value = {
    id: row.id,
    tenant: row.tenant,
    name: row.name,
    channel: row.channel,
    content: row.content,
    status: row.status,
  };
  dialog.value = true;
};

const submit = async () => {
  if (!form.value.tenant.trim() || !form.value.name.trim()) {
    ElMessage.warning('请填写租户与模板名');
    return;
  }
  submitting.value = true;
  try {
    if (form.value.id) {
      await updateTemplateApi({
        templateId: form.value.id,
        name: form.value.name.trim(),
        channel: form.value.channel,
        content: form.value.content,
        status: form.value.status,
      });
    } else {
      await createTemplateApi({
        tenant: form.value.tenant.trim(),
        name: form.value.name.trim(),
        channel: form.value.channel,
        content: form.value.content,
        status: form.value.status,
      });
    }
    ElMessage.success('模板已保存');
    dialog.value = false;
    await reload();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败');
  } finally {
    submitting.value = false;
  }
};

const toggle = async (row: MessageTemplateItem) => {
  const next = row.status === 'active' ? 'disabled' : 'active';
  await ElMessageBox.confirm(
    `确认将模板「${row.name}」${next === 'active' ? '启用' : '停用'}吗？`,
    '提示',
  );
  try {
    await setTemplateStatusApi({ templateId: row.id, status: next });
    ElMessage.success('模板状态已更新');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '更新失败');
  }
};

const remove = async (row: MessageTemplateItem) => {
  await ElMessageBox.confirm(`确认删除模板「${row.name}」吗？该操作不可恢复。`, '危险操作');
  await ElMessageBox.confirm('删除后累计到达统计一并消失，请再次确认', '二次确认');
  try {
    await deleteTemplateApi({ templateId: row.id });
    ElMessage.success('模板已删除');
    await reload();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败');
  }
};

const openSend = (row: MessageTemplateItem) => {
  if (row.status !== 'active') {
    ElMessage.warning('只有启用中的模板可以发送');
    return;
  }
  sendForm.value = { tenant: row.tenant, name: row.name, user_ref: '' };
  sendDialog.value = true;
};

const submitSend = async () => {
  if (!sendForm.value.user_ref.trim()) {
    ElMessage.warning('请填写接收方');
    return;
  }
  sending.value = true;
  try {
    const res = await sendNotifyApi({
      tenant: sendForm.value.tenant,
      name: sendForm.value.name,
      user_ref: sendForm.value.user_ref.trim(),
    });
    // 按真实回执提示：未送达就说未送达，不用 success 掩盖
    if (res.delivered) {
      ElMessage.success('已送达');
    } else {
      ElMessage.warning(`未送达：${res.reason}`);
    }
    sendDialog.value = false;
    await reload();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '发送失败');
  } finally {
    sending.value = false;
  }
};

onMounted(() => {
  load();
  loadReach();
});
</script>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.kw {
  width: 200px;
}

.kw-sm {
  width: 130px;
}

.kw-full {
  width: 100%;
}

.reach {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--reai-text-muted);
}

.reach-item b {
  color: var(--reai-text-main);
}

.reach-note {
  font-size: 12px;
}

.hint {
  color: var(--reai-text-muted);
  font-size: 12px;
}

.muted {
  color: var(--reai-text-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
