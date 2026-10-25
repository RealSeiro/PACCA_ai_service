-- AI 친구 서비스 · PostgreSQL 스키마 v2 (서버·DB 담당 김도현)
-- 기획안 v2 기준: 자유 대화 + 개인화 기억 + 인지 놀이 + 동의 기반 보호자 공유
-- 실행: psql -d anbu -f schema.sql

-- ⓪ 공유 항목 종류 ------------------------------------------------
-- 일상 기록·요약의 항목이자, 보호자 공유 동의의 단위. 새 항목은 행 하나 추가로 끝.
CREATE TABLE share_categories (
  code     TEXT PRIMARY KEY,               -- 'MEAL'
  label    TEXT NOT NULL,                  -- '식사'
  is_daily BOOLEAN NOT NULL DEFAULT true,  -- true = 대화에서 나온 일상 정보 항목 / false = 놀이 참여처럼 다른 데이터
  sort     SMALLINT NOT NULL DEFAULT 0
);
INSERT INTO share_categories (code, label, is_daily, sort) VALUES
  ('MEAL',     '식사',          true,  1),
  ('MOOD',     '기분',          true,  2),
  ('ACTIVITY', '활동',          true,  3),
  ('HEALTH',   '건강 관련 언급', true,  4),
  ('PLAY',     '놀이 참여',     false, 5);

-- ① 사람과 연결 -----------------------------------------------------
CREATE TABLE users (
  id            BIGSERIAL PRIMARY KEY,
  role          TEXT NOT NULL CHECK (role IN ('ELDER','GUARDIAN')),
  name          TEXT NOT NULL,
  email         TEXT UNIQUE,                 -- 보호자만
  password_hash TEXT,                        -- 보호자만 (원문 저장 금지)
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE care_links (                    -- 보호자 ↔ 어르신 (N:M)
  id          BIGSERIAL PRIMARY KEY,
  guardian_id BIGINT NOT NULL REFERENCES users(id),
  elder_id    BIGINT NOT NULL REFERENCES users(id),
  status      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','REVOKED')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (guardian_id, elder_id)
);

CREATE TABLE invite_codes (                  -- 어르신 앱이 만든 초대 코드 → 보호자가 입력
  code       CHAR(6) PRIMARY KEY,
  elder_id   BIGINT NOT NULL REFERENCES users(id),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at    TIMESTAMPTZ,
  used_by    BIGINT REFERENCES users(id)
);

CREATE TABLE consents (                      -- 연결마다 × 항목마다. 행이 없으면 '공유 안 함'
  link_id    BIGINT NOT NULL REFERENCES care_links(id),
  category   TEXT NOT NULL REFERENCES share_categories(code),
  granted    BOOLEAN NOT NULL DEFAULT false,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (link_id, category)
);

CREATE TABLE devices (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id),
  fcm_token    TEXT NOT NULL UNIQUE,
  last_seen_at TIMESTAMPTZ
);

-- ② 대화 -------------------------------------------------------------
CREATE TABLE conversations (                 -- 어르신이 시작한 대화 한 번 (예약 없음)
  id         BIGSERIAL PRIMARY KEY,
  elder_id   BIGINT NOT NULL REFERENCES users(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at   TIMESTAMPTZ,
  status     TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','ENDED'))
);
-- 한 어르신에게 진행 중인 대화는 하나만
CREATE UNIQUE INDEX one_active_conversation ON conversations (elder_id) WHERE status = 'ACTIVE';

CREATE TABLE turns (                         -- 말 한 마디. 보관 기간이 지나면 스케줄러가 지움
  id              BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  seq             INT NOT NULL,
  speaker         TEXT NOT NULL CHECK (speaker IN ('AI','ELDER')),
  text            TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (conversation_id, seq)
);

-- ③ 기억 -------------------------------------------------------------
CREATE TABLE memories (                      -- 관심사·선호·경험. 대화에서 실제로 나온 것만
  id              BIGSERIAL PRIMARY KEY,
  elder_id        BIGINT NOT NULL REFERENCES users(id),
  kind            TEXT NOT NULL CHECK (kind IN ('INTEREST','PREFERENCE','EXPERIENCE','PERSON','OTHER')),
  content         TEXT NOT NULL,             -- '젊을 때 남편과 제주도 신혼여행을 다녀옴'
  topic           TEXT,                      -- 'TRAVEL' 처럼 퀴즈 카테고리와 이어질 수 있는 주제 (선택)
  evidence        TEXT NOT NULL,             -- 근거가 된 어르신 말 (그대로 인용)
  source_conversation_id BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at    TIMESTAMPTZ,
  UNIQUE (elder_id, content)
);

-- ④ 놀이 -------------------------------------------------------------
CREATE TABLE quiz_questions (                -- 검증된 문제은행 (3분야 × 10문제)
  id         BIGSERIAL PRIMARY KEY,
  category   TEXT NOT NULL CHECK (category IN ('MUSIC','FOOD','TRAVEL')),
  question   TEXT NOT NULL,
  answer     TEXT NOT NULL,                  -- 대표 정답
  accepted   TEXT[] NOT NULL DEFAULT '{}',   -- 정답으로 인정할 다른 표현
  hint       TEXT,
  verified   BOOLEAN NOT NULL DEFAULT false, -- 팀 검수 완료 여부
  active     BOOLEAN NOT NULL DEFAULT true,
  UNIQUE (question)
);

CREATE TABLE play_sessions (                 -- 놀이 한 판
  id              BIGSERIAL PRIMARY KEY,
  elder_id        BIGINT NOT NULL REFERENCES users(id),
  conversation_id BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
  kind            TEXT NOT NULL CHECK (kind IN ('RECALL','QUIZ')),
  quiz_category   TEXT CHECK (quiz_category IN ('MUSIC','FOOD','TRAVEL')),
  memory_id       BIGINT REFERENCES memories(id) ON DELETE SET NULL,   -- 회상 놀이의 바탕이 된 기억
  current_question_id BIGINT REFERENCES quiz_questions(id),           -- 퀴즈: 지금 답을 기다리는 문제
  status          TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','COMPLETED','STOPPED')),
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at        TIMESTAMPTZ,
  CHECK (kind <> 'QUIZ' OR quiz_category IS NOT NULL)
);
CREATE UNIQUE INDEX one_active_play ON play_sessions (elder_id) WHERE status = 'ACTIVE';

CREATE TABLE quiz_answers (                  -- 퀴즈 답과 판정
  id              BIGSERIAL PRIMARY KEY,
  play_session_id BIGINT NOT NULL REFERENCES play_sessions(id) ON DELETE CASCADE,
  question_id     BIGINT NOT NULL REFERENCES quiz_questions(id),
  user_answer     TEXT NOT NULL,
  is_correct      BOOLEAN NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (play_session_id, question_id)
);

-- ⑤ 일상 -------------------------------------------------------------
CREATE TABLE daily_records (                 -- 대화에서 어르신이 직접 말한 일상 정보
  id              BIGSERIAL PRIMARY KEY,
  elder_id        BIGINT NOT NULL REFERENCES users(id),
  day             DATE NOT NULL,             -- 한국 날짜
  category        TEXT NOT NULL REFERENCES share_categories(code),
  content         TEXT NOT NULL,             -- '점심에 국수를 드심'
  evidence        TEXT NOT NULL,             -- 근거 발화
  source_conversation_id BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE daily_checks (                  -- 일상 확인 질문은 하루 최대 1번
  elder_id        BIGINT NOT NULL REFERENCES users(id),
  day             DATE NOT NULL,
  asked_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  conversation_id BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
  declined        BOOLEAN NOT NULL DEFAULT false,   -- 어르신이 답하기 싫다고 함
  PRIMARY KEY (elder_id, day)
);

CREATE TABLE daily_summaries (               -- 날짜별 요약. 항목별로 나눠 저장해야 동의별로 걸러 보여줄 수 있음
  elder_id   BIGINT NOT NULL REFERENCES users(id),
  day        DATE NOT NULL,
  category   TEXT NOT NULL REFERENCES share_categories(code),
  summary    TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (elder_id, day, category)
);

-- ⑥ 알림 -------------------------------------------------------------
CREATE TABLE notification_log (              -- 하루 1번 대화 알림. 같은 날 두 번 못 보내게 PK로 막음
  elder_id BIGINT NOT NULL REFERENCES users(id),
  day      DATE NOT NULL,
  sent_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered BOOLEAN NOT NULL DEFAULT false,
  PRIMARY KEY (elder_id, day)
);

-- 색인
CREATE INDEX ON turns (conversation_id, seq);
CREATE INDEX ON memories (elder_id, created_at DESC);
CREATE INDEX ON daily_records (elder_id, day);
CREATE INDEX ON play_sessions (elder_id, started_at);

-- ⑦ 퀴즈 문제은행 초안 30문제 ---------------------------------------
-- 담당자가 사실 확인을 했지만, 팀 검수 후 verified = true 로 바꾼다.
INSERT INTO quiz_questions (category, question, answer, accepted, hint) VALUES
-- 음악·트로트
('MUSIC', '"내 나이가 어때서"를 부른 가수는 누구일까요?', '오승근', '{}', '성이 오씨예요'),
('MUSIC', '"동백 아가씨"를 부른 가수는 누구일까요?', '이미자', '{}', '엘레지의 여왕이라고 불려요'),
('MUSIC', '"네 박자"를 부른 가수는 누구일까요?', '송대관', '{}', '"해뜰날"도 이분 노래예요'),
('MUSIC', '1982년에 나온 노래 "아파트"를 부른 가수는 누구일까요?', '윤수일', '{}', '윤수일 밴드로도 활동했어요'),
('MUSIC', '"칠갑산"을 부른 가수는 누구일까요?', '주병선', '{}', '성이 주씨예요'),
('MUSIC', '"사랑의 미로"를 부른 가수는 누구일까요?', '최진희', '{}', '성이 최씨인 여자 가수예요'),
('MUSIC', '"만남"을 부른 가수는 누구일까요?', '노사연', '{}', '"우리 만남은 우연이 아니야"로 시작해요'),
('MUSIC', '"돌아와요 부산항에"를 부른 가수는 누구일까요?', '조용필', '{가왕}', '가왕이라고 불려요'),
('MUSIC', '"남행열차"를 부른 가수는 누구일까요?', '김수희', '{}', '성이 김씨인 여자 가수예요'),
('MUSIC', '2020년 "내일은 미스터트롯" 첫 시즌의 우승자는 누구일까요?', '임영웅', '{영웅}', '"이제 나만 믿어요"를 불렀어요'),
-- 음식·요리
('FOOD', '동짓날에 먹는 붉은 죽은 무엇일까요?', '팥죽', '{동지팥죽}', '붉은 콩으로 쒀요'),
('FOOD', '정월 대보름에 딱딱한 견과류를 깨물어 먹는 풍습을 무엇이라고 할까요?', '부럼', '{부럼깨기}', '"부"로 시작해요'),
('FOOD', '추석에 빚어 먹는 반달 모양의 떡은 무엇일까요?', '송편', '{}', '솔잎을 깔고 쪄요'),
('FOOD', '설날 아침에 먹으면 나이를 한 살 먹는다고 하는 음식은 무엇일까요?', '떡국', '{}', '가래떡을 썰어 넣어요'),
('FOOD', '삼계탕의 주재료가 되는 고기는 무엇일까요?', '닭', '{닭고기,영계}', '"꼬끼오" 하고 울어요'),
('FOOD', '식혜를 만들 때 쓰는, 보리에 싹을 틔워 말린 가루는 무엇일까요?', '엿기름', '{엿기름가루,엿질금}', '"엿"으로 시작해요'),
('FOOD', '된장과 간장을 만들기 위해 콩을 삶아 뭉쳐서 띄운 덩어리는 무엇일까요?', '메주', '{}', '두 글자예요'),
('FOOD', '전주를 대표하는, 여러 나물을 얹어 비벼 먹는 음식은 무엇일까요?', '비빔밥', '{전주비빔밥}', '고추장을 넣고 비벼요'),
('FOOD', '춘천을 대표하는, 양념한 닭고기를 철판에 볶은 요리는 무엇일까요?', '닭갈비', '{춘천닭갈비}', '"닭"으로 시작해요'),
('FOOD', '초복, 중복, 말복 가운데 가장 먼저 오는 날은 무엇일까요?', '초복', '{}', '"처음"이라는 뜻의 글자가 들어가요'),
-- 여행·지역
('TRAVEL', '우리나라(남한)에서 가장 높은 산은 무엇일까요?', '한라산', '{}', '제주도에 있어요'),
('TRAVEL', '돌, 바람, 여자가 많다고 해서 제주도를 부르는 말은 무엇일까요?', '삼다도', '{삼다}', '"셋이 많다"는 뜻이에요'),
('TRAVEL', '불국사와 석굴암이 있는 도시는 어디일까요?', '경주', '{경주시}', '신라의 수도였어요'),
('TRAVEL', '해운대 해수욕장이 있는 도시는 어디일까요?', '부산', '{부산시,부산광역시}', '우리나라 제2의 도시예요'),
('TRAVEL', '울릉도 동쪽에 있는, 우리나라 동쪽 끝의 섬은 어디일까요?', '독도', '{}', '"독"으로 시작해요'),
('TRAVEL', '"한국의 나폴리"라고 불리는 경상남도의 항구 도시는 어디일까요?', '통영', '{통영시}', '충무김밥이 유명해요'),
('TRAVEL', '안동에 있는, 하회탈로 유명한 마을은 어디일까요?', '하회마을', '{하회,안동하회마을}', '"하회"로 시작해요'),
('TRAVEL', '전라남도 보성은 어떤 차 밭으로 유명할까요?', '녹차', '{녹차밭}', '초록색 차예요'),
('TRAVEL', '서울 남산 꼭대기에 있는 타워를 흔히 뭐라고 부를까요?', '남산타워', '{N서울타워,엔서울타워,서울타워}', '산 이름이 들어가요'),
('TRAVEL', '단양팔경으로 유명한 단양은 어느 도에 있을까요?', '충청북도', '{충북}', '바다가 없는 도예요');
