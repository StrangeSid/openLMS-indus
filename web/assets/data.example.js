// SPDX-License-Identifier: GPL-3.0-or-later
// Synthetic demo data, used when web/data.js is missing. Dates are relative to today.
(() => {
  const day = 86400000;
  const at = (days, hour = 18) => {
    const d = new Date(Date.now() + days * day);
    d.setHours(hour, 0, 0, 0);
    return d.toISOString();
  };
  const date = days => at(days).slice(0, 10);

  const courses = [
    { title: 'Mathematics: Analysis and Approaches', level: 'HL', code: 'MAA01', teacher: 'R. Iyer' },
    { title: 'Physics', level: 'HL', code: 'PHY01', teacher: 'K. Menon' },
    { title: 'Computer Science', level: 'HL', code: 'CS01', teacher: 'A. Thomas' },
    { title: 'English A: Language and Literature', level: 'SL', code: 'EN01', teacher: 'L. Fernandes' },
    { title: 'Business Management', level: 'HL', code: 'BM01', teacher: 'V. Rao' },
    { title: 'German ab initio', level: 'SL', code: 'GER01', teacher: 'F. Schmidt' },
  ].map((c, i) => ({ ...c, id: `demo-course-${i + 1}`, subject: c.title }));
  const teacher = s => courses.find(c => c.title.startsWith(s)).teacher;

  const eol = [
    ['Functions · Composite functions', 'Mathematics: Analysis And Approaches', 3, null],
    ['Kinematics · Projectile motion', 'Physics', 6, null],
    ['B2 · Searching algorithms', 'Computer Science', 1, null],
    ['Unit 2 · Marketing mix', 'Business Management', 12, null],
    ['Wortschatz · Essen und Trinken', 'German Ab Initio', -2, null],
    ['B2 · Looping statements', 'Computer Science', -4, null],
    ['Vectors · Dot product', 'Mathematics: Analysis And Approaches', -9, -10],
    ['Energy · Work and power', 'Physics', -12, -13],
  ].map(([title, subject, due, submitted], i) => ({
    id: `demo-eol-${i + 1}`, title, subject, topic: null, status: submitted ? 'graded' : 'assigned',
    score: submitted ? '4.00' : null, total: '5.00', teacher: teacher(subject.split(':')[0].split(' ')[0]),
    assigned: at(due - 7, 9), due: at(due), opens: at(due - 7, 9),
    submitted: submitted ? at(submitted, 16) : null, availability: due < 0 ? 'expired' : 'active',
    testId: `${subject.slice(0, 3).toUpperCase()}${String(100 + due + 20).padStart(3, '0')}`,
    canAttempt: due >= 0 && !submitted, expired: due < 0, blocked: false, suspended: false, exits: 0, exitMax: 3,
    expiresMessage: due < 0 ? 'This test has expired.' : null,
  }));

  const assessments = [
    ['Paper 1 practice', 'English A: Language And Literature', 'FA', 'Writing', 9, null, null],
    ['STEAM project brief', 'Computer Science', 'FA', 'STEAM', 14, null, null],
    ['SDL · Kinematics', 'Physics', 'SDL', null, -5, -6, '8.0'],
    ['Case study analysis', 'Business Management', 'FA', null, -15, -14, '15.0'],
    ['Leseverstehen', 'German Ab Initio', 'FA', 'Reading', -20, -21, '17.0'],
    ['Term 1 summative', 'Mathematics: Analysis And Approaches', 'SA', null, 18, null, null],
    ['Mechanics summative', 'Physics', 'SA', null, -8, -9, '16.0'],
  ].map(([title, subject, type, category, due, submitted, marks], i) => ({
    id: `demo-fa-${i + 1}`, questions: i === 0 ? 2 : 0, submissionOpen: true,
    title, subject, type, category, due: at(due), status: marks ? 'graded' : 'assigned', marks,
    total: '20', teacher: teacher(subject.split(':')[0].split(' ')[0]),
    submitted: submitted ? at(submitted, 15) : null, assigned: at(due - 10, 9),
  }));

  const tasks = [
    ['Lab report: free fall', 'Physics', 4, null],
    ['Commentary draft', 'English A: Language And Literature', 11, null],
    ['Market research survey', 'Business Management', -3, null],
    ['Vocabulary poster', 'German Ab Initio', -11, -12],
  ].map(([title, subject, due, submitted], i) => ({
    id: `demo-task-${i + 1}`, attachments: 1,
    title, subject, due: at(due), status: submitted ? 'submitted' : 'assigned',
    submitted: submitted ? at(submitted, 14) : null, assigned: at(due - 7, 9), teacher: teacher(subject.split(':')[0].split(' ')[0]),
  }));

  const announcements = [
    ['Revision worksheet posted', 'German Ab Initio', 'Please complete the worksheet before Friday.', 1, -1],
    ['Lab session moved', 'Physics', 'Thursday’s practical moves to Lab 2, period 5.', 0, -2],
    ['Unit test next week', 'Mathematics: Analysis And Approaches', 'Covers functions 2.1–2.6. Practice paper attached.', 1, -3],
    ['Reading for Monday', 'English A: Language And Literature', 'Read chapters 3–4 and note two stylistic features.', 0, -4],
    ['Project groups', 'Computer Science', 'Groups for the STEAM project are on the class board.', 0, -6],
  ].map(([title, subject, message, files, d], i) => ({
    id: `demo-ann-${i + 1}`, title, subject, message, html: `<p>${message}</p><p>Thanks,<br>${teacher(subject.split(':')[0].split(' ')[0])}</p>`,
    files: files ? [{ name: 'Practice paper.pdf', url: null }] : [], at: at(d, 10), by: teacher(subject.split(':')[0].split(' ')[0]),
  }));

  const folders = {
    'Mathematics: Analysis And Approaches': ['Unit 2: Functions', ['Functions practice.pdf', 'Functions notes.docx', 'Mark scheme.pdf']],
    'Physics': ['Mechanics', ['Kinematics notes.pdf', 'Projectile lab.docx', 'Formula sheet.pdf']],
    'Computer Science': ['B2 Programming', ['Searching algorithms.pptx', 'Drill and practice.docx', 'Tracing worksheet.pdf']],
    'English A: Language And Literature': ['Paper 1', ['Sample commentary.pdf', 'Annotation guide.docx']],
    'Business Management': ['Unit 2: Marketing', ['Marketing mix.pptx', 'Case study.pdf']],
    'German Ab Initio': ['Vokabeln', ['Essen und Trinken.pdf']],
  };
  const resources = Object.entries(folders).flatMap(([subject, [folder, names]]) =>
    names.map(name => ({ title: name, name, subject, folder, teacher: teacher(subject.split(':')[0].split(' ')[0]) })));

  const records = Array.from({ length: 20 }, (_, i) => ({ date: date(-28 + i), status: i % 9 === 4 ? 'absent' : 'present', subject: 'Homeroom' }));
  const present = records.filter(r => r.status === 'present').length;

  window.LMS = {
    student: 'Demo Student',
    programCode: 'DP',
    program: 'DP · Grade XI',
    year: '2026-27',
    courses, eol, assessments, tasks, announcements, resources,
    unread: 4,
    threads: [
      { userId: 'demo-t-phy', name: teacher('Physics'), role: 'TEACHER', last: 'Please bring your lab notebook tomorrow.', at: at(-0.2, 15) },
      { userId: 'demo-t-cs', name: teacher('Computer'), role: 'TEACHER', last: 'Groups are posted. Let me know if you want to swap.', at: at(-1, 17) },
      { userId: 'demo-t-eng', name: teacher('English'), role: 'TEACHER', last: 'Good draft! See my comments on paragraph two.', at: at(-3, 12) },
    ],
    notifications: [
      { id: 'demo-n-1', refId: 'demo-fa-2', title: 'New FA test: STEAM project brief', message: 'Your teacher published a new FA test.', type: 'fa', actor: teacher('Computer'), at: at(-1, 11), read: false, link: '/assignments/test/computer-science/fa', subject: 'Computer Science' },
      { id: 'demo-n-2', refId: 'demo-eol-1', title: 'New EOL test: Composite functions', message: 'A new end-of-lesson test is open.', type: 'eol', actor: teacher('Mathematics'), at: at(-2, 9), read: false, link: '/assignments/test/mathematics-analysis-and-approaches/eol', subject: 'Mathematics: Analysis and Approaches' },
      { id: 'demo-n-3', refId: 'demo-fa-3', title: 'Result published: SDL · Kinematics', message: 'Your work has been graded.', type: 'fa', actor: teacher('Physics'), at: at(-4, 14), read: true, link: '/assignments/test/physics/fa', subject: 'Physics' },
    ],
    attendance: { total_sessions: records.length, present, absent: records.length - present, late: 0, percentage: (present / records.length * 100).toFixed(1), records },
    calendar: [
      { date: date(3), end: date(3), type: 'no_school', label: 'No school' },
      { date: date(5), end: date(5), type: 'other_activity', label: 'Parent–teacher meeting' },
      { date: date(10), end: date(16), type: 'holiday', label: 'Mid-term break' },
      { date: date(17), end: date(17), type: 'other_activity', label: 'School reopens' },
    ],
    downloaded: false,
    demo: true,
    // Detail views for demo mode (what the server's /api routes return when signed in).
    demoDetail: {
      contacts: [
        { userId: 'demo-t-phy', name: teacher('Physics'), role: 'TEACHER', subjects: 'Physics' },
        { userId: 'demo-t-cs', name: teacher('Computer'), role: 'TEACHER', subjects: 'Computer Science' },
        { userId: 'demo-t-eng', name: teacher('English'), role: 'TEACHER', subjects: 'English A' },
        { userId: 'demo-t-maa', name: teacher('Mathematics'), role: 'TEACHER', subjects: 'Mathematics AA' },
        { userId: 'demo-coord', name: 'S. Kapoor', role: 'DP_COORDINATOR', subjects: 'DP Coordinator' },
      ],
      conversations: {
        'demo-t-phy': [
          { id: 'm1', mine: true, text: 'Hi, do we need the lab notebook for tomorrow?', at: at(-0.4, 14) },
          { id: 'm2', mine: false, text: 'Please bring your lab notebook tomorrow.', at: at(-0.2, 15) },
        ],
        'demo-t-cs': [{ id: 'm3', mine: false, text: 'Groups are posted. Let me know if you want to swap.', at: at(-1, 17) }],
        'demo-t-eng': [
          { id: 'm4', mine: true, text: 'I uploaded my commentary draft.', at: at(-3.5, 18) },
          { id: 'm5', mine: false, text: 'Good draft! See my comments on paragraph two.', at: at(-3, 12) },
        ],
      },
      eolQuestions: [
        { id: 'dq1', html: '<p>If <i>f(x) = 2x + 1</i> and <i>g(x) = x²</i>, what is <i>f(g(2))</i>?</p>', options: [
          { key: 'a', html: '9' }, { key: 'b', html: '25' }, { key: 'c', html: '5' }, { key: 'd', html: '10' }], correct: 'a' },
        { id: 'dq2', html: '<p>Which function is the inverse of <i>h(x) = 3x − 6</i>?</p>', options: [
          { key: 'a', html: 'x/3 − 6' }, { key: 'b', html: '(x + 6)/3' }, { key: 'c', html: '3x + 6' }, { key: 'd', html: '6 − 3x' }], correct: 'b' },
        { id: 'dq3', html: '<p>The domain of <i>√(x − 4)</i> is…</p>', options: [
          { key: 'a', html: 'x > 4' }, { key: 'b', html: 'x ≥ 0' }, { key: 'c', html: 'x ≥ 4' }, { key: 'd', html: 'all real x' }], correct: 'c' },
      ],
      faQuestions: [
        { id: 'fq1', type: 'mcq', html: '<p>Which device converts digital data into analogue signals?</p>', options: [
          { key: 'a', html: 'Router' }, { key: 'b', html: 'Modem' }, { key: 'c', html: 'Switch' }, { key: 'd', html: 'Hub' }] },
        { id: 'fq2', type: 'text', html: '<p>Explain one advantage of a linear search over a binary search.</p>', options: [] },
      ],
      policies: [
        { title: 'Academic Integrity Policy', description: 'Expectations for original work and citations.', url: null, version: '3' },
        { title: 'Assessment Policy', description: 'How work is assessed, deadlines and extensions.', url: null, version: '2' },
        { title: 'Language Policy', description: null, url: null, version: '1' },
      ],
    },
  };
})();
