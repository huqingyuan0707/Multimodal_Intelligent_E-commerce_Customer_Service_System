// API 唯一入口 barrel（对齐前端 Skill §3）：接口按域拆分为单独箭头函数文件，页面一律从 '@/api' 导入。
// 新增接口 = 在对应域文件里加一个 xxxApi 箭头函数：dispatch({method, systemId, path, params, idempotent}) → 判 code → 返回 data。
export * from './http';
export * from './auth';
export * from './goods';
export * from './inventory';
export * from './orders';
export * from './marketing';
export * from './logistics';
export * from './reviews';
export * from './approvals';
export * from './documents';
export * from './tasks';
export * from './chat';
export * from './workbench';
export * from './multimodal';
export * from './mining';
export * from './dashboard';
export * from './screen';
export * from './admin';
