// 采购协同接口（供应商 + 采购单状态机 + 到货质检；对齐 API 规范 §4.7 采购节 / 页面设计 §3.12）
// 后端无 prefix：路径即全路径 /api/v1/suppliers、/api/v1/purchase；行名/SKU 快照由服务端回填，前端只传 sku_id/qty/price。
import { dispatch, type Envelope } from './http';

const check = (res: Envelope) => {
  if (res.code !== 0) {
    throw new Error(res.msg);
  }
  return res.data;
};

// 供应商分页列表（名称模糊筛选）
export const listSuppliersApi = async (params?: {
  keyword?: string;
  page?: number;
  size?: number;
}) =>
  check(
    await dispatch({
      path: '/api/v1/suppliers',
      params: {
        keyword: params?.keyword ?? '',
        page: params?.page ?? 1,
        size: params?.size ?? 20,
      },
    }),
  );

// 新建供应商（合格率 0~1，页面层以百分比录入再换算）
export const createSupplierApi = async (params: {
  name: string;
  pay_terms?: string;
  pass_rate?: number;
}) =>
  check(
    await dispatch({
      method: 'POST',
      path: '/api/v1/suppliers',
      params: {
        name: params.name,
        pay_terms: params.pay_terms ?? '',
        pass_rate: params.pass_rate ?? 1,
      },
      idempotent: true,
    }),
  );

// 采购单分页列表（status 精确筛选；行含 status_label/allowed_actions 供置灰）
export const listPurchaseOrdersApi = async (params?: {
  status?: string;
  page?: number;
  size?: number;
}) =>
  check(
    await dispatch({
      path: '/api/v1/purchase',
      params: {
        status: params?.status ?? '',
        page: params?.page ?? 1,
        size: params?.size ?? 20,
      },
    }),
  );

// 建采购单（恒为草稿；金额单位分，前端按元录入换算）
export const createPurchaseOrderApi = async (params: {
  supplier_id: string;
  warehouse_id?: string;
  items: { sku_id: string; qty: number; price: number }[];
  eta?: string;
}) =>
  check(
    await dispatch({
      method: 'POST',
      path: '/api/v1/purchase',
      params: {
        supplier_id: params.supplier_id,
        warehouse_id: params.warehouse_id ?? '',
        items: params.items,
        eta: params.eta ?? '',
      },
      idempotent: true,
    }),
  );

// 采购审批不在此处：建单即同事务落审批中心（purchase.approve），批/驳统一走 /api/v1/approvals（见 api/approvals.ts）

// 到货登记（仅已审批；eta 为 YYYY-MM-DD，可空）
export const receivePurchaseOrderApi = async (params: { id: string; eta?: string }) =>
  check(
    await dispatch({
      method: 'POST',
      path: `/api/v1/purchase/${encodeURIComponent(params.id)}/receive`,
      params: { eta: params.eta ?? '' },
      idempotent: true,
    }),
  );

// 到货质检（passed=false 即退供；质检说明必填；合格须已指定收货仓才入库）
export const qcPurchaseOrderApi = async (params: { id: string; passed: boolean; note: string }) =>
  check(
    await dispatch({
      method: 'POST',
      path: `/api/v1/purchase/${encodeURIComponent(params.id)}/qc`,
      params: { passed: params.passed, note: params.note },
      idempotent: true,
    }),
  );
