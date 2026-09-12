// 演示兜底数据（后端不可用时回退，对齐前端 Skill §6；口径见页面设计 §4）
export type MockSession = {
  id: string;
  title: string;
};

export const mockSessions: MockSession[] = [
  { id: 't-demo-1', title: '演示会话：退换咨询' },
  { id: 't-demo-2', title: '演示会话：尺码推荐' },
];
