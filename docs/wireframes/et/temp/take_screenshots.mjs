// ET 模組 wireframe 截圖腳本
// 用法：cd wireframes/et/temp && node take_screenshots.mjs

import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { mkdirSync } from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const HTML_PATH = path.resolve(__dirname, '..', 'index.html');
const OUT_DIR = path.resolve(__dirname, 'screenshots');
const URL = pathToFileURL(HTML_PATH).href;

mkdirSync(OUT_DIR, { recursive: true });

// 隱藏：sidebar / 操作說明 / toast / 視角切換鈕 / 漢堡按鈕
const HIDE_CSS = `
  .sidebar { display: none !important; }
  .wf-screen-note { display: none !important; }
  .et-toast { display: none !important; }
  /* 隱藏視角切換 dropdown 與漢堡按鈕 */
  .navbar-tsbms .dropdown { display: none !important; }
  .navbar-tsbms > button:first-of-type { display: none !important; }
  body { padding-left: 0 !important; }
  .main-content { margin-left: 0 !important; padding: 1rem 1.5rem !important; }
  /* 凍結動畫，截圖時穩定 */
  *, *::before, *::after { transition: none !important; animation: none !important; }
`;

async function setup(page) {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(URL, { waitUntil: 'networkidle' });
  await page.addStyleTag({ content: HIDE_CSS });
  // 預設關掉 login overlay
  await page.evaluate(() => {
    const ov = document.getElementById('login-overlay');
    if (ov) ov.style.display = 'none';
  });
}

async function captureScreen(page, { screenId, filename, prep }) {
  if (screenId) {
    await page.evaluate((id) => {
      if (typeof goScreen === 'function') goScreen(id);
      else {
        document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
        const el = document.getElementById(id);
        if (el) el.classList.add('active');
      }
      window.scrollTo(0, 0);
    }, screenId);
  }

  if (prep) await prep(page);
  await page.waitForTimeout(300);

  const out = path.join(OUT_DIR, filename);
  const contentHeight = await page.evaluate(() => {
    const active = document.querySelector('.screen.active');
    if (!active) return 900;
    const rect = active.getBoundingClientRect();
    return Math.ceil(rect.bottom + window.scrollY + 24);
  });
  const height = Math.max(600, Math.min(contentHeight, 8000));
  await page.setViewportSize({ width: 1280, height });
  await page.waitForTimeout(120);
  await page.screenshot({ path: out, fullPage: false });
  console.log(`  ✓ ${filename}  (h=${height})`);
}

async function captureModal(page, { triggerScreenId, modalId, filename, prep }) {
  if (triggerScreenId) {
    await page.evaluate((id) => {
      if (typeof goScreen === 'function') goScreen(id);
      window.scrollTo(0, 0);
    }, triggerScreenId);
  }
  if (prep) await prep(page);

  // 先清除所有 modal 狀態
  await page.evaluate(() => {
    const M = window.bootstrap && window.bootstrap.Modal;
    document.querySelectorAll('.modal.show').forEach(el => {
      const inst = M && M.getInstance(el);
      if (inst) inst.hide();
      else el.classList.remove('show');
    });
    document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
    document.body.classList.remove('modal-open');
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';
  });
  await page.waitForTimeout(300);

  await page.evaluate((mid) => {
    const el = document.getElementById(mid);
    if (!el) return;
    const M = window.bootstrap && window.bootstrap.Modal;
    if (M) new M(el).show();
  }, modalId);
  await page.waitForTimeout(450);

  const out = path.join(OUT_DIR, filename);
  const measure = async () => page.evaluate((mid) => {
    const el = document.getElementById(mid);
    if (!el) return null;
    const content = el.querySelector('.modal-content');
    if (!content) return null;
    const r = content.getBoundingClientRect();
    return { x: Math.floor(r.left), y: Math.floor(r.top), w: Math.ceil(r.width), h: Math.ceil(r.height) };
  }, modalId);

  let dim = await measure();
  if (!dim) { console.log(`  ✗ ${filename} (modal not found)`); return; }

  const pad = 16;
  await page.setViewportSize({ width: 1280, height: Math.max(600, dim.h + pad * 2 + 40) });
  await page.waitForTimeout(150);
  dim = await measure();
  await page.screenshot({
    path: out,
    clip: {
      x: Math.max(0, dim.x - pad),
      y: Math.max(0, dim.y - pad),
      width: Math.min(1280 - Math.max(0, dim.x - pad), dim.w + pad * 2),
      height: dim.h + pad * 2,
    },
  });
  console.log(`  ✓ ${filename}  (modal ${dim.w}x${dim.h})`);
}

async function captureLogin(page, { step, filename }) {
  await page.evaluate((s) => {
    const ov = document.getElementById('login-overlay');
    if (ov) ov.style.display = '';
    if (typeof _loginShow === 'function') _loginShow(s);
  }, step);
  await page.waitForTimeout(300);

  const out = path.join(OUT_DIR, filename);
  const dim = await page.evaluate(() => {
    const card = document.querySelector('.login-overlay .login-card') || document.querySelector('.login-overlay > div');
    if (!card) return null;
    const r = card.getBoundingClientRect();
    return { x: Math.floor(r.left), y: Math.floor(r.top), w: Math.ceil(r.width), h: Math.ceil(r.height) };
  });
  if (dim) {
    const pad = 24;
    await page.setViewportSize({ width: 1280, height: Math.min(dim.h + 200, 1200) });
    await page.waitForTimeout(120);
    await page.screenshot({
      path: out,
      clip: {
        x: Math.max(0, dim.x - pad),
        y: Math.max(0, dim.y - pad),
        width: Math.min(1280, dim.w + pad * 2),
        height: dim.h + pad * 2,
      },
    });
  } else {
    await page.screenshot({ path: out, fullPage: false });
  }
  console.log(`  ✓ ${filename}  (login step=${step})`);
}

const TASKS = [
  // ========== 主畫面 ==========
  { kind: 'screen', screenId: 'et-courses-admin', filename: 'ET01_課程列表_教師.png',
    prep: async (page) => {
      await page.evaluate(() => { if (typeof filterCourses === 'function') filterCourses('all'); });
      await page.waitForTimeout(150);
    },
  },

  { kind: 'screen', screenId: 'et-course-create', filename: 'ET02_課程新增.png' },

  { kind: 'screen', screenId: 'et-course-create-success', filename: 'ET02_課程已建立.png',
    prep: async (page) => {
      await page.evaluate(() => {
        if (typeof showCourseCreatedSuccess === 'function') showCourseCreatedSuccess('draft');
      });
      await page.waitForTimeout(200);
    },
  },

  { kind: 'screen', screenId: 'et-course-edit', filename: 'ET02_課程編輯_owner.png',
    prep: async (page) => {
      await page.evaluate(() => {
        sessionStorage.setItem('et02CourseName', '採血作業新進人員訓練 v2.0');
        sessionStorage.setItem('et02CreatorName', '陳大華');
        sessionStorage.setItem('et02IsOwner', '1');
        sessionStorage.setItem('et02IsClosed', '0');
        if (typeof applyEt02Mode === 'function') applyEt02Mode();
      });
      await page.waitForTimeout(200);
    },
  },

  { kind: 'screen', screenId: 'et-course-edit', filename: 'ET02_課程檢視_非owner.png',
    prep: async (page) => {
      await page.evaluate(() => {
        sessionStorage.setItem('et02CourseName', '捐血人健康評估標準教學');
        sessionStorage.setItem('et02CreatorName', '林助教');
        sessionStorage.setItem('et02IsOwner', '0');
        sessionStorage.setItem('et02IsClosed', '0');
        if (typeof applyEt02Mode === 'function') applyEt02Mode();
      });
      await page.waitForTimeout(200);
    },
  },

  { kind: 'screen', screenId: 'et-course-edit', filename: 'ET02_課程檢視_已停課.png',
    prep: async (page) => {
      await page.evaluate(() => {
        sessionStorage.setItem('et02CourseName', 'BS04 領血掃血袋實務培訓');
        sessionStorage.setItem('et02CreatorName', '陳大華');
        sessionStorage.setItem('et02IsOwner', '1');
        sessionStorage.setItem('et02IsClosed', '1');
        if (typeof applyEt02Mode === 'function') applyEt02Mode();
      });
      await page.waitForTimeout(200);
    },
  },

  { kind: 'screen', screenId: 'et-students', filename: 'ET03_學員_已加入.png',
    prep: async (page) => {
      await page.evaluate(() => {
        const link = document.querySelector('a[href="#students-joined"]');
        if (link) link.click();
      });
      await page.waitForTimeout(200);
    },
  },

  { kind: 'screen', screenId: 'et-students', filename: 'ET03_學員_待加入.png',
    prep: async (page) => {
      await page.evaluate(() => {
        const link = document.querySelector('a[href="#students-invited"]');
        if (link) link.click();
      });
      await page.waitForTimeout(200);
    },
  },

  { kind: 'screen', screenId: 'et-courses-student', filename: 'ET04_我的課程_學員.png' },

  { kind: 'screen', screenId: 'et-learn', filename: 'ET05_課程學習.png' },

  { kind: 'screen', screenId: 'et-quiz-intro', filename: 'ET06_測驗開始引導.png' },

  { kind: 'screen', screenId: 'et-quiz', filename: 'ET06_測驗作答.png',
    prep: async (page) => {
      // 預設隱藏結果區
      await page.evaluate(() => {
        const r = document.getElementById('quiz-result');
        if (r) r.style.display = 'none';
      });
      await page.waitForTimeout(150);
    },
  },

  { kind: 'screen', screenId: 'et-quiz', filename: 'ET06_測驗結果.png',
    prep: async (page) => {
      await page.evaluate(() => {
        if (typeof showQuizResult === 'function') showQuizResult();
      });
      await page.waitForTimeout(300);
    },
  },

  { kind: 'screen', screenId: 'et-permissions', filename: 'ET07_權限管理.png' },

  { kind: 'screen', screenId: 'et-profile', filename: 'ET08_個人資料維護.png' },

  // ========== Modal ==========
  { kind: 'modal', triggerScreenId: 'et-course-edit', modalId: 'chapterModal',
    filename: 'ET02_modal_章節新增.png',
    prep: async (page) => {
      await page.evaluate(() => {
        sessionStorage.setItem('et02IsOwner', '1');
        sessionStorage.setItem('et02IsClosed', '0');
        if (typeof applyEt02Mode === 'function') applyEt02Mode();
      });
    },
  },

  { kind: 'modal', triggerScreenId: 'et-course-edit', modalId: 'materialModal',
    filename: 'ET02_modal_教材編輯.png',
    prep: async (page) => {
      await page.evaluate(() => {
        sessionStorage.setItem('et02IsOwner', '1');
        sessionStorage.setItem('et02IsClosed', '0');
        if (typeof applyEt02Mode === 'function') applyEt02Mode();
      });
    },
  },

  { kind: 'modal', triggerScreenId: 'et-course-edit', modalId: 'quizModal',
    filename: 'ET02_modal_測驗編輯.png',
    prep: async (page) => {
      await page.evaluate(() => {
        sessionStorage.setItem('et02IsOwner', '1');
        sessionStorage.setItem('et02IsClosed', '0');
        if (typeof applyEt02Mode === 'function') applyEt02Mode();
      });
    },
  },

  { kind: 'modal', triggerScreenId: 'et-course-edit', modalId: 'inviteModal',
    filename: 'ET02_modal_邀請學員.png',
    prep: async (page) => {
      await page.evaluate(() => {
        sessionStorage.setItem('et02IsOwner', '1');
        sessionStorage.setItem('et02IsClosed', '0');
        if (typeof applyEt02Mode === 'function') applyEt02Mode();
      });
    },
  },

  { kind: 'modal', triggerScreenId: 'et-course-edit', modalId: 'closeCourseModal',
    filename: 'ET02_modal_停課確認.png',
    prep: async (page) => {
      await page.evaluate(() => {
        sessionStorage.setItem('et02IsOwner', '1');
        sessionStorage.setItem('et02IsClosed', '0');
        if (typeof applyEt02Mode === 'function') applyEt02Mode();
      });
    },
  },

  { kind: 'modal', triggerScreenId: 'et-students', modalId: 'resetQuizModal',
    filename: 'ET03_modal_重置重考次數.png',
    prep: async (page) => {
      await page.evaluate(() => {
        const el = document.getElementById('reset-quiz-user');
        if (el) el.textContent = '王曉明';
      });
    },
  },

  { kind: 'modal', triggerScreenId: 'et-students', modalId: 'removeStudentModal',
    filename: 'ET03_modal_移除學員.png',
    prep: async (page) => {
      await page.evaluate(() => {
        const el = document.getElementById('remove-student-user');
        if (el) el.textContent = '王曉明';
      });
    },
  },

  { kind: 'modal', triggerScreenId: 'et-courses-student', modalId: 'joinCourseModal',
    filename: 'ET04_modal_加入新課程.png' },

  { kind: 'modal', triggerScreenId: 'et-permissions', modalId: 'moduleAssignmentModal',
    filename: 'ET07_modal_模組對應設定.png',
    prep: async (page) => {
      await page.evaluate(() => {
        if (typeof openModuleModal === 'function') {
          // 設好使用者名稱即可，modal show 由 captureModal 處理
          const el = document.getElementById('module-modal-user');
          if (el) el.textContent = '李主任';
        }
      });
    },
  },

  { kind: 'modal', triggerScreenId: 'et-profile', modalId: 'etPasswordChangeModal',
    filename: 'ET08_modal_變更密碼.png' },

  // ========== 登入頁 ==========
  { kind: 'login', step: 'login-step-1', filename: '登入頁_登入.png' },
  { kind: 'login', step: 'login-register', filename: '登入頁_註冊.png' },
  { kind: 'login', step: 'login-forgot-1', filename: '登入頁_忘記密碼.png' },
];

(async () => {
  console.log(`Source : ${URL}`);
  console.log(`Output : ${OUT_DIR}`);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await setup(page);
  for (const t of TASKS) {
    try {
      if (t.kind === 'screen') await captureScreen(page, t);
      else if (t.kind === 'modal') await captureModal(page, t);
      else if (t.kind === 'login') await captureLogin(page, t);
    } catch (e) {
      console.error(`  ✗ ${t.filename}: ${e.message}`);
    }
  }
  await browser.close();
  console.log('Done.');
})();
