// 转人工 composable：买家自助挂起（POST handoff，owner 口）+ 本地 t- 占位先落库
// 链路：ChatView → 本模块 → api（createSessionApi/handoffSessionApi）+ stores/session（占位认领）；对齐页面设计 §3.1
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import { createSessionApi, handoffWorkbenchApi } from '@/api';
import { useSessionStore } from '@/stores/session';

export const useHumanHandoff = () => {
  const transferring = ref(false);

  // 转人工：无后端会话（t- 占位/空）先建会话认领，再挂起进待接队列；成功追加系统提示行
  const transfer = async (appendSystem: (content: string) => unknown) => {
    if (transferring.value) return;
    transferring.value = true;
    try {
      const store = useSessionStore();
      const localId = store.currentId;
      let sid = localId ?? '';
      if (!sid || sid.startsWith('t-')) {
        const created = await createSessionApi({ title: '转人工会话' });
        if (localId) {
          store.adoptSession(localId, created.id, created.title ?? '');
        }
        sid = created.id;
      }
      await handoffWorkbenchApi({ id: sid, reason: '买家主动请求人工' });
      appendSystem('已为你转人工，坐席将在 30 秒内接管，请留意回复。');
    } catch (e) {
      ElMessage.error((e as Error).message || '转人工失败，请稍后重试');
    } finally {
      transferring.value = false;
    }
  };

  return { transferring, transfer };
};
