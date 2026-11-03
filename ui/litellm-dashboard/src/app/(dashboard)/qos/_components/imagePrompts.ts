export type ImagePrompt = { id: string; text: string; check: string; negative_prompt?: string };

export type ImageRating = {
  prompt_adherence: number;
  text_correct: boolean | null;
  artifacts: boolean | null;
  notes: string;
  structure_correctness: number | null;
  text_accuracy: number | null;
  text_applicable: boolean | null;
  image_quality: number | null;
  visual_appeal: number | null;
  hard_conditions_passed: boolean | null;
  defect_tags: DefectTag[];
  quality_score: number | null;
};

export type ImageRatingInput = Omit<ImageRating, "quality_score">;

export type DefectTag = "count" | "spatial" | "text" | "hands" | "perspective" | "fusion" | "artifacts" | "style" | "other";

export type ImageItem = {
  id: string;
  prompt_id: string;
  prompt: string;
  check: string;
  negative_prompt: string | null;
  seed: number;
  status: "pending" | "success" | "failure";
  e2e_s: number | null;
  response_s: number | null;
  queue_s: number | null;
  run_s: number | null;
  cost_cny: number | null;
  task_id: string | null;
  image_file: string | null;
  error: string | null;
  rating: ImageRating | null;
};

export type ImageRun = {
  id: string;
  model: string;
  status: "running" | "complete" | "interrupted";
  started_at: string;
  finished_at: string | null;
  concurrency: number;
  size: string;
  unit_cost_cny: number;
  estimated_cost_cny: number;
  supports_seed: boolean;
  items: ImageItem[];
};

export type ImageHomeSummary = {
  window_started_at: string;
  window_ended_at: string;
  runs: number;
  requests: number;
  successful: number;
  failed: number;
  pending: number;
  p95_e2e_s: number | null;
  estimated_cost_cny: number;
  rated: number;
  mean_quality_score: number | null;
  models: string[];
};

export type ImageModelProfile = {
  unit_cost_cny: number;
  supports_seed: boolean;
  supports_negative_prompt: boolean;
  max_prompt_chars: number;
};

export type ImageConfig = {
  max_images: number;
  models: Record<string, ImageModelProfile>;
};

export type ImagePlan = {
  model: string;
  prompts: readonly ImagePrompt[];
  seeds: readonly number[];
  concurrency: number;
  size: "1024x1024";
  max_cost_cny: number;
};

export const IMAGE_PROMPTS: readonly ImagePrompt[] = [
  { id: "zh_text_sign", text: "一家老式茶馆的木质招牌，招牌上用金色书法写着「沐曦茶馆」四个字，傍晚暖色灯光", check: "四字正确、无缺笔，傍晚暖光" },
  { id: "zh_text_poster", text: "极简风格海报，白色背景，中央是黑色粗体大字「国产算力」，下方一行小字「2026 上海」", check: "两行文字完整且准确" },
  { id: "en_text_neon", text: "A neon sign on a red brick wall that says OPEN 24 HOURS, rainy night, reflections on the wet street", check: "OPEN 24 HOURS 准确" },
  { id: "count_color", text: "白色桌面上整齐摆放着三个红苹果和两个青苹果，俯拍，纯白背景", check: "红苹果 3 个、青苹果 2 个" },
  { id: "spatial", text: "A blue cube to the left of a yellow sphere, both on a wooden table, studio lighting", check: "蓝色立方体在左，黄色球在右" },
  { id: "portrait_hands", text: "一位老奶奶双手捧着一杯热茶，近景特写，能看清每根手指，自然窗光", check: "手指数量和形状正常，脸部无畸变" },
  { id: "photo_bund", text: "上海外滩夜景，黄浦江上有一艘游船，远处是东方明珠塔，长曝光摄影", check: "建筑可辨认，灯光和水面反射自然" },
  { id: "anime_girl", text: "日系动漫风格，一个穿校服的女孩坐在樱花树下读书，柔和的粉色调", check: "风格一致，线条干净" },
  { id: "product_glass", text: "一瓶透明玻璃香水瓶放在白色大理石台面上，背景虚化，商业产品摄影", check: "玻璃透明感、折射和高光合理" },
  { id: "macro_cat_eye", text: "微距特写一只橘猫的眼睛，能看清虹膜纹理和胡须", check: "细节清晰，无格纹或噪点" },
  { id: "dense_market", text: "熙熙攘攘的菜市场，摊位上摆满各种蔬菜水果，很多顾客和摊主", check: "物体和人物结构合理，无大面积崩坏" },
  { id: "landscape_mist", text: "A misty mountain valley at sunrise with a winding river, wide angle landscape photograph", check: "天空和雾气过渡平滑，无色带" },
  { id: "flat_gradient", text: "纯色渐变背景，从深蓝色平滑过渡到橙色，画面中没有任何物体", check: "过渡平滑无色带" },
  { id: "low_light", text: "漆黑的房间里只有桌上一支蜡烛的光，周围物体隐约可见", check: "暗部无彩色噪点、无整片发灰" },
  { id: "negative_ramen", text: "一碗热腾腾的日式拉面，俯拍，木质桌面，画面中不要出现筷子和勺子", check: "画面里不应出现筷子和勺子" },
  { id: "long_prompt", text: "清晨的江南水乡，青石板路沿着小河延伸，河上停着一条乌篷船，船头站着一位穿蓝印花布衣服的船娘，岸边有白墙黛瓦的民居，墙角开着几丛红色的月季，远处石拱桥上有一个撑油纸伞的行人，薄雾，水墨淡彩风格", check: "逐项核对船、船娘、蓝印花布、月季、石拱桥和撑伞行人" },
];

export const SMOKE_PROMPTS = IMAGE_PROMPTS.slice(0, 2);
