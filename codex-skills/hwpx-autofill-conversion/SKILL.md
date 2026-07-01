---
name: hwpx-autofill-conversion
description: hwpx 양식을 첨부하면 첨부 양식에 맞춰 주제를 작성. hwpx 파일 생성, 수정, 내용 채우기 요청 시 반드시 사용.
---

# hwpx 양식 자동 채우기

첨부된 hwpx 파일을 분석하여 XML 구조에 맞게 주제에 맞는 내용을 작성하고 hwpx 파일로 출력합니다.

---

## hwpx 파일 구조

hwpx는 ZIP 형식의 패키지 파일입니다.

### 최상위 구조
- `mimetype`: HWPX 패키지 명시 (application/hwp+zip)
- `version.xml`: 버전 정보
- `settings.xml`: 보기 배율, 호환성, 언어 설정

### META-INF/ 폴더
- `manifest.xml`: 내부 파일 경로 및 MIME Type 목록
- `container.xml`, `container.rdf`: 컨테이너 정의

### BinData/ 폴더
이미지, 도형, OLE 객체 등 바이너리 데이터

### Preview/ 폴더
- `PrvImage.png`: 문서 미리보기 이미지
- `PrvText.txt`: 문서 텍스트 미리보기

### Contents/ 폴더 (핵심 데이터)
- `content.hpf`: 패키지 전체 명세서
- `header.xml`: 글꼴, 문단 스타일 등 전역 서식
- `section0.xml` 등: 실제 본문 (`<hp:p>` 문단, `<hp:t>` 텍스트)

---

## 작업 절차

### 1단계: 원본 파일 분석
```bash
cp /mnt/user-data/uploads/파일명.hwpx /home/claude/template.hwpx
unzip -o template.hwpx -d template_extracted/
cat template_extracted/Preview/PrvText.txt   # 구조 파악
cat template_extracted/Contents/section0.xml # 본문 XML 분석
```

### 2단계: 내용 작성 (Python으로 XML 텍스트 교체)
```python
with open('template_extracted/Contents/section0.xml', 'r', encoding='utf-8') as f:
    content = f.read()

# <hp:t> 태그 내부 텍스트만 교체 (서식 태그 구조는 절대 수정 금지)
content = content.replace('<hp:t>기존텍스트</hp:t>', '<hp:t>새텍스트</hp:t>')

with open('report_extracted/Contents/section0.xml', 'w', encoding='utf-8') as f:
    f.write(content)
```

### 3단계: hwpx 파일 패키징 ⚠️ 매우 중요

> **파일 손상의 주요 원인**: `zip` 명령어로 단순 패키징하면 내부 파일 순서와 압축 flag가 원본과 달라져 한글(HWP)이 파일을 손상된 것으로 인식합니다.

**반드시 아래 Python 코드로 패키징해야 합니다:**

```python
import zipfile, os

src_dir = '/home/claude/report_extracted'
output_path = '/home/claude/output.hwpx'

# 원본에서 zip 메타정보(순서, 압축방식, flag) 읽기
with zipfile.ZipFile('/home/claude/template.hwpx', 'r') as orig:
    orig_order = [(info.filename, info.compress_type, info.flag_bits)
                  for info in orig.infolist()]

# 동일한 순서·설정으로 새 파일 생성
with zipfile.ZipFile(output_path, 'w') as zout:
    for filename, compress_type, flag_bits in orig_order:
        filepath = os.path.join(src_dir, filename)
        if os.path.isfile(filepath):
            info = zipfile.ZipInfo(filename)
            info.compress_type = compress_type
            info.flag_bits = flag_bits  # UTF-8 flag 등 원본과 동일하게 유지
            with open(filepath, 'rb') as f:
                data = f.read()
            zout.writestr(info, data)
```

**❌ 절대 사용 금지 (파일 손상 발생):**
```bash
# zip 명령어는 파일 순서와 flag가 달라져 HWP에서 손상 파일로 인식됨
zip -r output.hwpx mimetype META-INF BinData Contents ...
```

**핵심 이유:**
- hwpx는 ZIP 포맷이지만 내부 파일 **순서**와 각 파일의 `compress_type`, `flag_bits`가 원본과 정확히 일치해야 함
- `mimetype`은 압축 없이(compress_type=0), 원본 순서 그대로 첫 번째에 위치해야 함
- `flag_bits=4`는 UTF-8 파일명을 의미하며 원본과 다르면 파일명 인식 오류 발생

---

## XML 수정 규칙

- `<hp:t>` 태그 내부 텍스트만 수정
- 속성값(ID, 크기, 위치 등) 수정 금지
- 서식 태그(`<hp:run>`, `<hp:p>` 등) 구조 변경 금지
- 특수문자 XML 이스케이프: `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`

---

## 최종 출력

```bash
cp /home/claude/output.hwpx /mnt/user-data/outputs/결과파일.hwpx
```

완성 후 `present_files` 도구로 사용자에게 제공.
