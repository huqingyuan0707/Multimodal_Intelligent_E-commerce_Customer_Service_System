// 图片上传（≤9 张/单张 ≤10M/JPG-PNG-WEBP/超限 canvas 压缩；上传走 uploadImageApi，对齐页面设计 §4）
import { ref } from 'vue';
import { uploadImageApi } from '@/api';

export type PendingImage = {
  id: string;
  preview: string;
  file: File;
  status: 'ready' | 'uploading' | 'done' | 'error';
};

const MAX_COUNT = 9;
const MAX_SIZE = 10 * 1024 * 1024;
const MAX_EDGE = 1280;

const compress = (file: File) =>
  new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, MAX_EDGE / Math.max(img.width, img.height));
      if (scale >= 1 && file.size <= MAX_SIZE) {
        resolve(file);
        return;
      }
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        resolve(file);
        return;
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        blob => {
          if (!blob) {
            resolve(file);
            return;
          }
          resolve(new File([blob], file.name.replace(/\.\w+$/, '.jpg'), { type: 'image/jpeg' }));
        },
        'image/jpeg',
        0.82,
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('图片解码失败'));
    };
    img.src = url;
  });

export const useImageUpload = () => {
  const images = ref<PendingImage[]>([]);
  const error = ref('');

  const addFiles = async (files: FileList | File[]) => {
    error.value = '';
    const list = [...files];
    if (images.value.length + list.length > MAX_COUNT) {
      error.value = `最多传 ${MAX_COUNT} 张图`;
      return;
    }
    for (const f of list) {
      if (!/^image\/(jpeg|png|webp)$/.test(f.type)) {
        error.value = '仅支持 JPG/PNG/WEBP';
        continue;
      }
      try {
        const file = (await compress(f)) as File;
        images.value = [
          ...images.value,
          {
            id: `img-${Date.now()}-${images.value.length}`,
            preview: URL.createObjectURL(file),
            file,
            status: 'ready',
          },
        ];
      } catch {
        error.value = '有图片解码失败，已跳过';
      }
    }
  };

  const remove = (id: string) => {
    const found = images.value.find(i => i.id === id);
    if (found) {
      URL.revokeObjectURL(found.preview);
    }
    images.value = images.value.filter(i => i.id !== id);
  };

  // 逐张上传，返回服务端确认的文件名；失败的标 error 继续发文字
  const uploadAll = async () => {
    const names: string[] = [];
    for (const img of images.value) {
      if (img.status === 'done') {
        continue;
      }
      img.status = 'uploading';
      try {
        const res = await uploadImageApi({ file: img.file });
        img.status = 'done';
        names.push(res.filename);
      } catch {
        img.status = 'error';
      }
    }
    return names;
  };

  const clear = () => {
    images.value.forEach(i => URL.revokeObjectURL(i.preview));
    images.value = [];
  };

  return { images, error, addFiles, remove, uploadAll, clear };
};
