// useImageUpload 单测（上传即检测：file_id/inspection 透传 + 失败标 error，对齐前端 Skill §8）
// node 环境无 DOM：绕过 addFiles（需 createObjectURL），直接预置 images 后测 uploadAll。
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { uploadAndInspectImageApi } from '@/api';
import { useImageUpload } from './useImageUpload';

vi.mock('@/api', () => ({
  uploadAndInspectImageApi: vi.fn(),
}));

const fakeFile = (name: string) => ({ name, size: 10 }) as unknown as File;

const seed = (n: number, status = 'ready') => {
  const { images, uploadAll } = useImageUpload();
  images.value = Array.from({ length: n }, (_, i) => ({
    id: `img-${i}`,
    preview: '',
    file: fakeFile(`破洞-${i}.jpg`),
    status,
  })) as never;
  return { images, uploadAll };
};

describe('useImageUpload uploadAll', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('成功回 file_id/inspection 并置 done', async () => {
    vi.mocked(uploadAndInspectImageApi).mockResolvedValue({
      file_id: 'f1',
      inspection: { category: '破洞', confidence: 0.85, need_human: false },
    } as never);
    const { images, uploadAll } = seed(1);
    const done = await uploadAll();
    expect(done).toEqual([
      { file_id: 'f1', inspection: { category: '破洞', confidence: 0.85, need_human: false } },
    ]);
    expect(images.value[0]?.status).toBe('done');
  });

  it('失败标 error 且不阻断文字发送', async () => {
    vi.mocked(uploadAndInspectImageApi).mockRejectedValue(new Error('net'));
    const { images, uploadAll } = seed(1);
    const done = await uploadAll();
    expect(done).toEqual([]);
    expect(images.value[0]?.status).toBe('error');
  });

  it('done 状态跳过不重复上传', async () => {
    vi.mocked(uploadAndInspectImageApi).mockResolvedValue({ file_id: 'f9' } as never);
    const { uploadAll } = seed(1, 'done');
    const done = await uploadAll();
    expect(done).toEqual([]);
    expect(uploadAndInspectImageApi).not.toHaveBeenCalled();
  });
});
