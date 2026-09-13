<template>
  <div class="page">
    <h2>营销会员</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="优惠活动" name="promo">
        <div class="toolbar">
          <AiButton v-permission="['shop', 'admin']" type="primary" @click="openCreate">
            新建活动
          </AiButton>
        </div>
        <el-empty v-if="!promos.length && !loading" description="暂无活动" />
        <el-table v-loading="loading" :data="promos" style="width: 100%">
          <el-table-column prop="name" label="活动" min-width="160" />
          <el-table-column label="预算/已发/剩余" min-width="180">
            <template #default="s">{{ s.row.budget }} / {{ s.row.granted }} / {{ s.row.remaining }}</template>
          </el-table-column>
          <el-table-column label="有效期" min-width="200">
            <template #default="s">{{ validRange(s.row) }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="操作" width="160">
            <template #default="s">
              <AiButton v-permission="['cs', 'shop', 'admin']" link @click="openGrant(s.row)">
                发券
              </AiButton>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="会员" name="member">
        <div class="toolbar">
          <AiInput v-model="memberRef" placeholder="会员标识（如手机号后四位）" clearable />
          <AiButton @click="loadMember">查询</AiButton>
        </div>
        <el-descriptions v-if="member" :column="3" border>
          <el-descriptions-item label="标识">{{ member.user_ref }}</el-descriptions-item>
          <el-descriptions-item label="等级">{{ member.level }}</el-descriptions-item>
          <el-descriptions-item label="积分">{{ member.points }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="member" class="toolbar">
          <AiInput v-model="delta" placeholder="增减分（负数为扣）" />
          <AiButton v-permission="['shop', 'admin']" @click="adjust">调整积分</AiButton>
        </div>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="dialog" title="新建活动" width="440px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="名称">
          <AiInput v-model="form.name" />
        </el-form-item>
        <el-form-item label="预算(张)">
          <AiInput v-model="form.budget" />
        </el-form-item>
        <el-form-item label="生效起">
          <AiInput v-model="form.valid_from" placeholder="YYYY-MM-DD HH:mm:ss，可空=不限" />
        </el-form-item>
        <el-form-item label="生效止">
          <AiInput v-model="form.valid_to" placeholder="YYYY-MM-DD HH:mm:ss，可空=不限" />
        </el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="dialog = false">取消</AiButton>
        <AiButton type="primary" :loading="submitting" @click="submit">创建</AiButton>
      </template>
    </el-dialog>
    <el-dialog v-model="grantDialog" title="发券安抚" width="440px">
      <el-form :model="grantForm" label-width="90px">
        <el-form-item label="用户标识">
          <AiInput v-model="grantForm.user_ref" />
        </el-form-item>
        <el-form-item label="关联订单">
          <AiInput v-model="grantForm.order_ref" placeholder="可空" />
        </el-form-item>
      </el-form>
      <template #footer>
        <AiButton @click="grantDialog = false">取消</AiButton>
        <AiButton type="primary" :loading="granting" @click="submitGrant">发券</AiButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 营销会员：活动列表/创建 + 发券（幂等键本地生成，超预算 3006 中文提示）+ 会员查调分
// 对齐 FRD FR-10.6/附录 D、页面设计 §3.16
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import {
  adjustPointsApi,
  createPromoApi,
  getMemberApi,
  grantCouponApi,
  listPromosApi,
} from '@/api';
import AiButton from '@/shared/components/AiButton.vue';
import AiInput from '@/shared/components/AiInput.vue';
import type { MemberItem, PromoItem } from '@/types/shop';

const tab = ref('promo');
const promos = ref<PromoItem[]>([]);
const loading = ref(false);
const dialog = ref(false);
const submitting = ref(false);
const form = ref({ name: '', budget: '', valid_from: '', valid_to: '' });
const grantDialog = ref(false);
const granting = ref(false);
const grantPromo = ref<PromoItem | null>(null);
const grantForm = ref({ user_ref: '', order_ref: '' });
const memberRef = ref('');
const member = ref<MemberItem | null>(null);
const delta = ref('');

const loadPromos = async () => {
  loading.value = true;
  try {
    promos.value = await listPromosApi();
  } catch (e) {
    promos.value = [];
    ElMessage.error(e instanceof Error ? e.message : '加载活动失败');
  } finally {
    loading.value = false;
  }
};

const openCreate = () => {
  form.value = { name: '', budget: '', valid_from: '', valid_to: '' };
  dialog.value = true;
};

const validRange = (row: PromoItem) => {
  if (row.valid_from && row.valid_to) {
    return `${row.valid_from} ~ ${row.valid_to}`;
  }
  return row.valid_from ? `${row.valid_from} 起` : row.valid_to ? `至 ${row.valid_to}` : '不限';
};

const submit = async () => {
  if (!form.value.name || !Number(form.value.budget)) {
    ElMessage.warning('请填写名称与正数预算');
    return;
  }
  submitting.value = true;
  try {
    await createPromoApi({
      name: form.value.name,
      budget: Number(form.value.budget),
      valid_from: form.value.valid_from.trim() || undefined,
      valid_to: form.value.valid_to.trim() || undefined,
    });
    ElMessage.success('活动已创建');
    dialog.value = false;
    await loadPromos();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '创建失败');
  } finally {
    submitting.value = false;
  }
};

const openGrant = (row: PromoItem) => {
  grantPromo.value = row;
  grantForm.value = { user_ref: '', order_ref: '' };
  grantDialog.value = true;
};

const submitGrant = async () => {
  if (!grantPromo.value || !grantForm.value.user_ref) {
    ElMessage.warning('请填写用户标识');
    return;
  }
  await ElMessageBox.confirm(`确认从「${grantPromo.value.name}」发券吗？`, '提示');
  granting.value = true;
  try {
    // 幂等键： promo + 用户 + 时间戳，同单重复提交由后端回放去重
    const idemKey = `${grantPromo.value.id}:${grantForm.value.user_ref}:${Date.now()}`;
    await grantCouponApi({
      promoId: grantPromo.value.id,
      user_ref: grantForm.value.user_ref,
      order_ref: grantForm.value.order_ref,
      idemKey,
    });
    ElMessage.success('发券成功');
    grantDialog.value = false;
    await loadPromos();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '发券失败');
  } finally {
    granting.value = false;
  }
};

const loadMember = async () => {
  if (!memberRef.value) {
    ElMessage.warning('请填写会员标识');
    return;
  }
  try {
    member.value = await getMemberApi({ userRef: memberRef.value });
  } catch (e) {
    member.value = null;
    ElMessage.error(e instanceof Error ? e.message : '查询失败');
  }
};

const adjust = async () => {
  if (!member.value || !Number(delta.value)) {
    ElMessage.warning('请先查询会员并填写非零分值');
    return;
  }
  await ElMessageBox.confirm(`确认调整 ${delta.value} 分吗？`, '提示');
  try {
    member.value = await adjustPointsApi({
      userRef: member.value.user_ref,
      delta: Number(delta.value),
    });
    ElMessage.success('积分已更新');
    delta.value = '';
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '调整失败');
  }
};

onMounted(() => {
  loadPromos();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
</style>
