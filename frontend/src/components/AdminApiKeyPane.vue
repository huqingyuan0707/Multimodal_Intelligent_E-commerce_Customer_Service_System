<template>
  <div>
    <div class="toolbar">
      <AiInput v-model="tenant" placeholder="租户编码（空=全部）" class="kw" />
      <AiInput v-model="status" placeholder="状态 active/disabled" class="kw-sm" />
      <AiButton @click="reload">查询</AiButton>
      <AiButton v-permission="['admin']" type="primary" @click="openCreate">新建密钥</AiButton>
    </div>
    <p class="hint">
      明文只在创建/轮换那一刻返回一次（库里只存摘要，事后谁也取不出来）；列表永远只显示掩码。
      轮换会让旧口令立刻失效，调用方需同步更换。
    </p>
    <el-table v-loading="loading" :data="rows" style="width: 100%">
      <el-table-column prop="tenant" label="租户" min-width="120" />
      <el-table-column prop="name" label="用途" min-width="120" />
      <el-table-column label="密钥" min-width="200">
        <template #default="s">
          <span class="mono">{{ s.row.masked }}</span>
        </template>
      </el-table-column>
      <el-table-column label="Scope" min-width="140">
        <template #default="s">{{ (s.row.scopes ?? []).join(',') || '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="s">
          <el-tag :type="s.row.expired ? 'danger' : apiKeyStatusTagOf(s.row.status)" size="small">
            {{ s.row.expired ? '已过期' : s.row.status_label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="到期" min-width="120">
        <template #default="s">{{ s.row.expires_at || '永不过期' }}</template>
      </el-table-column>
      <el-table-column prop="rotated_at" label="最近轮换" min-width="150" />
      <el-table-column label="操作" width="150">
        <template #default="s">
          <AiButton v-permission="['admin']" link @click="rotate(s.row)">轮换</AiButton>
          <AiButton v-permission="['admin']" link @click="toggle(s.row)">
            {{ s.row.status === 'active' ? '禁用' : '启用' }}
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

    <el-dialog v-model="dialog" title="新建密钥" width="460px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="租户"><AiInput v-model="form.tenant" /></el-form-item>
        <el-form-item label="用途名"
          ><AiInput v-model="form.name" placeholder="如 订单同步"
        /></el-form-item>
        <el-form-item label="Scope"
          ><AiInput v-model="form.scopes" placeholder="逗号分隔，如 order:read,stock:read"
        /></el-form-item>
        <el-form-item label="到期日"
          ><AiInput v-model="form.expires_at" placeholder="YYYY-MM-DD，留空=永不过期"
        /></el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="dialog = false">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submit">创建</AiButton>
      </template>
    </el-dialog>

    <el-dialog
      v-model="plainDialog"
      title="请立即保存密钥（仅显示这一次）"
      width="520px"
      :close-on-click-modal="false"
    >
      <p class="warn">关闭本窗口后将无法再次查看：服务端只保存摘要，连管理员也取不回明文。</p>
      <div class="plain-box">
        <span class="mono plain">{{ plaintext }}</span>
      </div>
      <p class="hint">用途：{{ plainName }}</p>
      <template #footer>
        <AiButton @click="copyPlain">{{ copied ? '已复制' : '复制' }}</AiButton>
        <AiButton type="primary" @click="plainDialog = false">我已保存</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 密钥窗格（FR-8「密钥（只显掩码）」）：列表只回掩码；创建/轮换后的明文装进独立弹窗，
// 让用户来得及复制 —— 明文库里不存在，刷新即永久丢失，所以必须显式提示「仅显示一次」。
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import { createApiKeyApi, listApiKeysApi, rotateApiKeyApi, setApiKeyStatusApi } from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import { apiKeyStatusTagOf } from '@/types/admin';
import type { AdminApiKeyItem } from '@/types/admin';

const rows = ref<AdminApiKeyItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const tenant = ref('');
const status = ref('');
const loading = ref(false);
const submitting = ref(false);
const dialog = ref(false);
const form = ref({ tenant: '', name: '', scopes: 'read', expires_at: '' });
// 一次性明文弹窗：plaintext 只在 create/rotate 的响应里存在，关掉即不可再取
const plainDialog = ref(false);
const plaintext = ref('');
const plainName = ref('');
const copied = ref(false);

const load = async () => {
  loading.value = true;
  try {
    const res = await listApiKeysApi({
      tenant: tenant.value.trim(),
      status: status.value.trim(),
      page: page.value,
      size: size.value,
    });
    rows.value = res.items;
    total.value = res.total;
  } catch (e) {
    rows.value = [];
    total.value = 0;
    ElMessage.error(e instanceof Error ? e.message : '加载密钥失败');
  } finally {
    loading.value = false;
  }
};

const reload = () => {
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

const openCreate = () => {
  form.value = { tenant: '', name: '', scopes: 'read', expires_at: '' };
  dialog.value = true;
};

const showPlain = (name: string, value: string) => {
  plainName.value = name;
  plaintext.value = value;
  copied.value = false;
  plainDialog.value = true;
};

const submit = async () => {
  if (!form.value.tenant.trim() || !form.value.name.trim()) {
    ElMessage.warning('请填写租户与用途名');
    return;
  }
  submitting.value = true;
  try {
    const res = await createApiKeyApi({
      tenant: form.value.tenant.trim(),
      name: form.value.name.trim(),
      scopes: form.value.scopes.trim(),
      expires_at: form.value.expires_at.trim(),
    });
    dialog.value = false;
    showPlain(res.item.name, res.plaintext);
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '创建失败');
  } finally {
    submitting.value = false;
  }
};

const rotate = async (row: AdminApiKeyItem) => {
  // 轮换是不可逆且影响线上的操作（旧口令当场失效）：双重确认
  await ElMessageBox.confirm(
    `轮换「${row.name}」后旧口令立刻失效，调用方需同步更换，确认继续？`,
    '危险操作',
  );
  await ElMessageBox.confirm('旧密钥将无法恢复，请再次确认', '二次确认');
  try {
    const res = await rotateApiKeyApi({ keyId: row.id });
    showPlain(res.item.name, res.plaintext);
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '轮换失败');
  }
};

const toggle = async (row: AdminApiKeyItem) => {
  const next = row.status === 'active' ? 'disabled' : 'active';
  await ElMessageBox.confirm(
    `确认将「${row.name}」${next === 'disabled' ? '禁用' : '启用'}吗？`,
    '提示',
  );
  try {
    await setApiKeyStatusApi({ keyId: row.id, status: next });
    ElMessage.success('密钥状态已更新');
    await load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '更新失败');
  }
};

const copyPlain = async () => {
  try {
    await navigator.clipboard.writeText(plaintext.value);
    copied.value = true;
  } catch {
    // 非 HTTPS 或浏览器拒绝剪贴板权限：退化为手动复制，不谎报成功
    ElMessage.warning('浏览器未授权剪贴板，请手动选中复制');
  }
};

onMounted(() => {
  load();
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
  width: 150px;
}

.hint {
  color: var(--reai-text-muted);
  font-size: 12px;
  margin: 0 0 8px;
}

.mono {
  font-family: var(--reai-font-mono);
}

.plain-box {
  background: var(--reai-surface-light);
  border: 1px solid var(--reai-border);
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
}

.plain {
  color: var(--reai-text-on-light);
  font-size: 14px;
  word-break: break-all;
}

.warn {
  color: var(--reai-notice);
  font-size: 13px;
  margin: 0 0 8px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
