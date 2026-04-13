
const raw       = document.getElementById('examData').textContent;
const examData  = JSON.parse(raw);

const QUESTIONS      = examData.questions;
const SESSION_ID     = examData.sessionId;
const EXAM_ID        = examData.examId;
const MAX_VIOLATIONS = examData.maxViolations;

// ─── State ─────────────────────────────────────────────────
let remaining  = examData.remaining;
let current    = 0;
let answers    = {};       // { questionId: 'A' | 'B' | 'C' | 'D' }
let violCount  = examData.violations;
let terminated = false;

// ─── Initialise saved answers ───────────────────────────────
QUESTIONS.forEach(function(q) {
  if (q.saved) {
    answers[q.id] = q.saved;
  }
});

// ─── Render current question ────────────────────────────────
function render() {
  var q = QUESTIONS[current];

  document.getElementById('qNum').textContent =
    'Question ' + (current + 1) + ' of ' + QUESTIONS.length;

  document.getElementById('qText').textContent = q.text;

  var optsEl = document.getElementById('qOptions');
  optsEl.innerHTML = '';

  ['A', 'B', 'C', 'D'].forEach(function(key) {
    var map = { 'A': q.option_a, 'B': q.option_b, 'C': q.option_c, 'D': q.option_d };
    var text = map[key];
    if (!text) return;

    var isSelected = (answers[q.id] === key);

    var label = document.createElement('div');
    label.className = 'option-label' + (isSelected ? ' selected' : '');
    label.setAttribute('data-qid', q.id);
    label.setAttribute('data-key', key);

    var keyBox = document.createElement('div');
    keyBox.className = 'option-key';
    keyBox.textContent = key;

    var span = document.createElement('span');
    span.textContent = text;

    label.appendChild(keyBox);
    label.appendChild(span);

    label.addEventListener('click', function() {
      selectAnswer(q.id, key);
    });

    optsEl.appendChild(label);
  });

  updateNavButtons();
}

// ─── Select an answer ───────────────────────────────────────
function selectAnswer(questionId, key) {
  answers[questionId] = key;
  saveAnswer(questionId, key);
  render();
}

// ─── Save answer to server ──────────────────────────────────
function saveAnswer(questionId, key) {
  fetch('/api/save_answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id:  SESSION_ID,
      question_id: questionId,
      answer:      key
    })
  });
}

// ─── Update navigator buttons ───────────────────────────────
function updateNavButtons() {
  QUESTIONS.forEach(function(q, i) {
    var btn = document.getElementById('qbtn-' + i);
    if (!btn) return;

    btn.className = 'q-nav-btn';
    if (i === current) {
      btn.className += ' current';
    } else if (answers[q.id]) {
      btn.className += ' answered';
    }
  });

  var prevBtn = document.getElementById('prevBtn');
  var nextBtn = document.getElementById('nextBtn');

  if (prevBtn) prevBtn.disabled = (current === 0);
  if (nextBtn) nextBtn.style.display = (current === QUESTIONS.length - 1) ? 'none' : '';
}

// ─── Navigate questions ─────────────────────────────────────
function navigate(direction) {
  var next = current + direction;
  if (next >= 0 && next < QUESTIONS.length) {
    current = next;
    render();
  }
}

function goTo(index) {
  current = index;
  render();
}

// ─── Submit exam ────────────────────────────────────────────
function submitExam() {
  if (confirm('Are you sure you want to submit the exam? This cannot be undone.')) {
    window.location.href = '/exam/submit/' + EXAM_ID;
  }
}

// ─── Countdown timer ────────────────────────────────────────
function tick() {
  if (terminated) return;

  remaining--;

  if (remaining <= 0) {
    window.location.href = '/exam/submit/' + EXAM_ID;
    return;
  }

  var minutes = Math.floor(remaining / 60);
  var seconds = remaining % 60;
  var display = String(minutes).padStart(2, '0') + ':' + String(seconds).padStart(2, '0');

  var timerEl = document.getElementById('timer');
  timerEl.textContent = display;

  timerEl.className = 'timer-display';
  if (remaining < 300) {
    timerEl.className += ' danger';
  } else if (remaining < 600) {
    timerEl.className += ' warning';
  }

  setTimeout(tick, 1000);
}

// ─── Webcam ──────────────────────────────────────────────────
function startWebcam() {
  navigator.mediaDevices.getUserMedia({ video: true })
    .then(function(stream) {
      var video = document.getElementById('webcam');
      if (video) video.srcObject = stream;
    })
    .catch(function() {
      logViolation('webcam_denied', 'Camera access was denied');
    });
}

document.addEventListener('DOMContentLoaded', function() {
  if (document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen().catch(function() {});
  }

  startWebcam();
  setTimeout(checkWebcam, 5000);      // ← add this
  setInterval(function() {            // ← add this
    var video = document.getElementById('webcam');
    if (!video || !video.srcObject) {
      logViolation('webcam_off', 'Camera was turned off during exam');
    }
  }, 30000);

  render();
  setTimeout(tick, 1000);
});

// Check webcam after 5 seconds — if still no stream, log violation
function checkWebcam() {
  var video = document.getElementById('webcam');
  if (!video || !video.srcObject) {
    logViolation('webcam_denied', 'Camera was not enabled by student');
  }
}

setTimeout(checkWebcam, 5000);  // check after 5 seconds

// Check webcam every 30 seconds
setInterval(function() {
  var video = document.getElementById('webcam');
  if (!video || !video.srcObject) {
    logViolation('webcam_off', 'Camera was turned off during exam');
  }
}, 30000);



// ─── Show violation toast ────────────────────────────────────
function showToast(message) {
  var toast = document.getElementById('vToast');
  if (!toast) return;
  toast.textContent = '⚠ ' + message;
  toast.style.display = 'block';
  setTimeout(function() {
    toast.style.display = 'none';
  }, 3000);
}

// ─── Log violation to server ─────────────────────────────────
function logViolation(type, desc) {
  if (terminated) return;

  fetch('/api/violation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: SESSION_ID,
      type:       type,
      desc:       desc
    })
  })
  .then(function(response) {
    return response.json();
  })
  .then(function(data) {
    violCount = data.count;

    var violEl = document.getElementById('violCount');
    if (violEl) {
      violEl.textContent = violCount + ' / ' + MAX_VIOLATIONS;
    }

    showToast(desc);

    if (data.terminated) {
    terminated = true;
    // Disable all inputs immediately
    document.querySelectorAll('.option-label').forEach(function(el) {
        el.style.pointerEvents = 'none';
        el.style.opacity = '0.5';
    });
    document.querySelectorAll('button').forEach(function(el) {
        el.disabled = true;
    });
    alert(
        '⚠ EXAM TERMINATED\n\n' +
        'You have exceeded the maximum number of violations (' + MAX_VIOLATIONS + ').\n' +
        'The exam has been ended automatically.'
    );
    window.location.href = '/dashboard';
    }
  })
  .catch(function(err) {
    console.error('Violation logging failed:', err);
  });
}

// ─── Proctoring event listeners ──────────────────────────────

// Tab switch / window hide
document.addEventListener('visibilitychange', function() {
  if (document.hidden) {
    logViolation('tab_switch', 'Student switched tabs or minimized the window');
  }
});

// Fullscreen exit
document.addEventListener('fullscreenchange', function() {
  if (!document.fullscreenElement) {
    logViolation('fullscreen_exit', 'Student exited fullscreen mode');
  }
});

// Block copy
document.addEventListener('copy', function(e) {
  e.preventDefault();
  logViolation('copy_attempt', 'Attempted to copy exam content');
});

// Block right-click
document.addEventListener('contextmenu', function(e) {
  e.preventDefault();
});

// Block keyboard shortcuts
document.addEventListener('keydown', function(e) {
  if (e.ctrlKey || e.metaKey) {
    var blocked = ['c', 'v', 'a', 'p', 'u', 's'];
    if (blocked.indexOf(e.key.toLowerCase()) !== -1) {
      e.preventDefault();
      logViolation('keyboard_shortcut', 'Used restricted keyboard shortcut: Ctrl+' + e.key.toUpperCase());
    }
  }
});

// ─── Start everything on page load ───────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  // Request fullscreen
  if (document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen().catch(function() {
      // User may deny fullscreen, that's OK
    });
  }

  startWebcam();
  render();
  setTimeout(tick, 1000);
});