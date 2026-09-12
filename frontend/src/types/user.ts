// 用户与登录态类型（api 层与 store 共用，禁止各文件自造形状，对齐 API 规范 §4.1）
// 本项目「角色即权限」：perms 与 roles 同源，roles 供菜单/路由过滤，perms 供按钮级判断。
export type AppUser = {
  name: string;
  tenant: string;
  roles: string[];
  perms: string[];
};

// 登录接口返回：token 存 sessionStorage.reai_token
export type LoginResult = {
  token: string;
  user: AppUser;
};
