---
name: badge-background-templates
description: Generate beautiful 95mm×120mm pure background templates for ID cards, name badges, conference passes, and credentials. Pure backgrounds only - NO text, NO logos, NO icons, NO QR codes, NO placeholders. Focus on rich gradients, organic blobs, geometric mosaics, crystalline facets, watercolor washes, halftone patterns, and layered depth. Output is always SVG with real mm dimensions, ready for print.
---

# Badge Background Template Generator

## 🎯 핵심 규칙 (Core Rules)

### CANVAS (캔버스)
- **사이즈**: 95mm × 120mm (세로형, portrait)
- **SVG viewBox**: `"0 0 95 120"`
- **SVG attributes**: `width="95mm" height="120mm"`
- **비율**: 19:24 (portrait)

### ❌ 절대 포함하지 않는 것
- 텍스트 (회사명, 이름, 이벤트명 등)
- 로고 / 브랜드 마크
- 아이콘 (전화, 이메일, 위치 등)
- QR 코드 / 바코드
- 사진 플레이스홀더 (원형 아바타 등)
- "YOUR LOGO", "COMPANY NAME" 같은 더미 텍스트

### ✅ 반드시 포함하는 것
- 그라디언트 (최소 2-stop, 대부분 3+ stop 권장)
- 형상 요소 (유기적 블롭, 기하학적 조각, 파도, 결정체 중 택 1 이상)
- 깊이 표현 (레이어 / 투명도 / 블러 / 섀도우 / 노이즈 중 최소 2가지)
- 명확한 시각적 무게 배치 (top-heavy, bottom-heavy, diagonal, centered, corner-loaded)

---

## 🎨 디자인 아키타입 (Design Archetypes)

각 템플릿은 아래 아키타입 중 **하나**를 명확히 선택해 실행한다. 중간 지점은 피한다.

### 1. Watercolor Aurora (수채화 오로라)
- **분위기**: 부드럽고 몽환적, 에테리얼
- **기법**: 여러 겹의 블러된 블롭을 multiply/soft-light로 블렌딩 + 노이즈 텍스처
- **구도**: 상단 집중, 하단으로 옅어지는 페이드
- **추천 팔레트**: 파스텔 핑크/블루/퍼플/피치

### 2. Bauhaus Mosaic (바우하우스 모자이크)
- **분위기**: 생동감 있고 장난스러운 기하학
- **기법**: 원, 반원, 사각형, 삼각형을 타일처럼 배치. 플랫 컬러 + 얇은 아웃라인 허용
- **구도**: 코너 집중 (bottom-left 또는 top-right), 중앙은 비움
- **추천 팔레트**: 머스터드 / 코랄 / 네이비 / 크림 / 민트

### 3. Liquid Neon (리퀴드 네온)
- **분위기**: 다이내믹하고 미래적, 나이트클럽 감성
- **기법**: 대형 유기적 블롭 + 네온 글로우 + 다크 배경
- **구도**: S자 플로우, 전면 배치
- **추천 팔레트**: 일렉트릭 마젠타 / 시안 / 퍼플 / 블랙

### 4. Crystal Prism (크리스털 프리즘)
- **분위기**: 차갑고 정제된, 아이스/글래스
- **기법**: 투명도가 다른 삼각형 패싯을 겹침 (빛 굴절 느낌)
- **구도**: 대각선 흐름, 비대칭
- **추천 팔레트**: 틸 / 네이비 / 스카이블루 + 미묘한 펄 화이트

### 5. Halftone Sunset (하프톤 선셋)
- **분위기**: 레트로 1970-80s, 선샤인 팝
- **기법**: 스위핑 곡선 + 하프톤 도트 패턴 + 뜨거운 그라디언트
- **구도**: 곡선이 캔버스를 분할, 도트가 트랜지션 영역에 집중
- **추천 팔레트**: 선셋 오렌지 / 핫핑크 / 딥퍼플

### 6. Organic Jungle (오가닉 정글)
- **분위기**: 자연적이고 생명력 있는
- **기법**: 잎사귀 같은 유기적 형태, 깊은 녹색 톤
- **구도**: 테두리 두르기 (프레임 효과)
- **추천 팔레트**: 에메랄드 / 포레스트 / 세이지 / 크림

### 7. Minimal Arc (미니멀 아크)
- **분위기**: 고급스럽고 정제된 여백의 미
- **기법**: 큰 단일 곡선/원호 1-2개, 광대한 네거티브 스페이스
- **구도**: 80% 빈 공간 + 20% 시그니처 요소
- **추천 팔레트**: 오프화이트 + 단일 악센트 컬러 (테라코타, 세이지, 더스티 블루)

### 8. Retrowave Grid (레트로웨이브 그리드)
- **분위기**: 사이버펑크, 80s 네온 노스탤지어
- **기법**: 원근감 있는 그리드 + 태양/달 원형 + 스캔라인
- **구도**: 지평선 분할 (상하)
- **추천 팔레트**: 핫핑크 / 시안 / 퍼플 / 오렌지

---

## 🎨 팔레트 라이브러리 (Palette Library)

```
PAL-01 Watercolor Pastels:  #FFD6E0 #E0E7FF #F0D9FF #FFE5D0
PAL-02 Bauhaus Bold:        #F4A261 #E76F51 #264653 #2A9D8F #E9C46A
PAL-03 Neon Cyberpunk:      #FF006E #8338EC #3A86FF #FB5607 #FFBE0B
PAL-04 Ocean Crystal:       #03045E #0077B6 #00B4D8 #90E0EF #CAF0F8
PAL-05 Sunset Magenta:      #F72585 #B5179E #7209B7 #3A0CA3 #4361EE
PAL-06 Earth Terracotta:    #DDB892 #B08968 #7F5539 #9C6644 #E6CCB2
PAL-07 Jewel Tones:         #5F0F40 #9A031E #FB8B24 #E36414 #0F4C5C
PAL-08 Mint Forest:         #D8F3DC #95D5B2 #52B788 #2D6A4F #1B4332
PAL-09 Rose Gold:           #FFE4E1 #FFC9D0 #FFB6C1 #E78A93 #C06C84
PAL-10 Arctic Mono:         #F8F9FA #DEE2E6 #ADB5BD #6C757D #343A40
PAL-11 Tropical Punch:      #F15BB5 #FEE440 #00BBF9 #00F5D4 #9B5DE5
PAL-12 Deep Luxe:           #0A0E27 #1B263B #415A77 #778DA9 #E0E1DD
```

---

## 🛠 기술 레시피 (Technical Recipes)

### 수채화 블러 효과
```svg
<filter id="watercolor">
  <feGaussianBlur stdDeviation="3" />
</filter>
<filter id="grain">
  <feTurbulence baseFrequency="0.9" numOctaves="2" />
  <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.1 0"/>
  <feComposite in2="SourceGraphic" operator="in"/>
</filter>
```

### 네온 글로우
```svg
<filter id="glow">
  <feGaussianBlur stdDeviation="2" result="blur"/>
  <feMerge>
    <feMergeNode in="blur"/>
    <feMergeNode in="SourceGraphic"/>
  </feMerge>
</filter>
```

### 하프톤 도트 패턴
```svg
<pattern id="halftone" x="0" y="0" width="3" height="3" patternUnits="userSpaceOnUse">
  <circle cx="1.5" cy="1.5" r="0.6" fill="#000" opacity="0.3"/>
</pattern>
```

### 유기적 블롭 곡선 (예시)
```svg
<path d="M 20,30 C 40,10 70,20 80,50 C 90,80 60,100 40,90 C 10,80 5,50 20,30 Z"/>
```

---

## 📋 프롬프트 템플릿 (Prompt Template)

다량 생성 시 아래 구조로 명령:

```
95x120mm 순수 배경 템플릿 SVG를 만들어줘.
- 아키타입: [Watercolor Aurora / Bauhaus Mosaic / Liquid Neon / Crystal Prism / Halftone Sunset / Organic Jungle / Minimal Arc / Retrowave Grid]
- 팔레트: [PAL-XX 또는 커스텀 HEX 코드 배열]
- 구도 무게: [top-heavy / bottom-heavy / diagonal / corner-loaded / centered]
- 강조 효과: [noise / glow / blur / halftone / outline] (2개 이상 선택)
- 금지 요소: 텍스트, 로고, 아이콘, QR, 플레이스홀더 전부 제외
- viewBox="0 0 95 120"
```

### 배치 생성 예시
```
다음 8개 변형 템플릿을 각각 SVG로:
1. Watercolor Aurora + PAL-01 + top-heavy
2. Bauhaus Mosaic + PAL-02 + corner-loaded
3. Liquid Neon + PAL-03 + centered
4. Crystal Prism + PAL-04 + diagonal
5. Halftone Sunset + PAL-05 + bottom-heavy
6. Organic Jungle + PAL-08 + corner-loaded
7. Minimal Arc + PAL-06 + top-heavy
8. Retrowave Grid + PAL-11 + centered
```

---

## ✅ 품질 체크리스트

- [ ] viewBox가 정확히 `"0 0 95 120"`인가
- [ ] 텍스트 요소(`<text>`)가 **단 하나도** 없는가
- [ ] 아이콘/로고/QR/플레이스홀더 전혀 없는가
- [ ] 그라디언트가 최소 하나 이상 사용되었는가
- [ ] 레이어링이 최소 3단 이상 있는가 (배경 + 메인 + 악센트)
- [ ] 아키타입의 정체성이 명확히 드러나는가 (애매한 중간지점이 아닌가)
- [ ] 팔레트가 조화롭고 명도 대비가 있는가
- [ ] 인쇄 시 출혈(bleed) 여유를 위해 가장자리까지 디자인이 꽉 찼는가
- [ ] 파일명 규칙: `template_[archetype]_[paletteNum]_[composition].svg`

---

## 🎨 레이어링 원칙

좋은 배경은 **최소 3단 깊이**를 가진다:

1. **Base Layer**: 전체를 덮는 그라디언트 또는 단색
2. **Mid Layer**: 주요 형상 요소 (블롭, 기하학, 웨이브) - 캔버스의 30-70%
3. **Accent Layer**: 작은 디테일 (도트, 선, 작은 도형, 글로우) - 전체의 5-15%
4. **Texture Layer** (선택): 노이즈, 그레인, 블러 효과 - 전체 overlay

---

## 🚫 회피해야 할 것 (Anti-patterns)

- ❌ 평범한 대각선 그라디언트만 쓴 "AI 느낌" 배경
- ❌ 보라색-분홍 그라디언트 + 백색 = 클리셰
- ❌ 좌우 대칭의 지루한 구도
- ❌ 어느 아키타입인지 분간 안 되는 어정쩡한 혼합
- ❌ 너무 적은 레이어 (단색 + 블롭 하나)
- ❌ 톤이 모두 비슷한 저대비 팔레트

---

## 🎯 컨퍼런스/대학 특화 변형

계명대학교 / 장춘대학교 / 공자학원 등 학술 행사용은 아래 서브카테고리 추천:

- **아카데믹 엘레강스**: Minimal Arc + PAL-12 Deep Luxe
- **문화교류 축제**: Bauhaus Mosaic + PAL-11 Tropical Punch
- **국제 세미나**: Watercolor Aurora + PAL-04 Ocean Crystal
- **수여식/명예박사**: Crystal Prism + PAL-07 Jewel Tones
- **젊은 청년 행사**: Halftone Sunset + PAL-03 Neon Cyberpunk

---

*이 스킬은 기본 레이아웃 생성 후, 후속 단계에서 텍스트·로고·QR 등을 오버레이하는 워크플로우를 전제로 설계됨.*
