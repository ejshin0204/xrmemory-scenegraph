# GitHub 업로드

README.md가 있는 폴더를 저장소 루트로 사용한다.

GitHub에서 빈 저장소를 만든 뒤 아래 YOUR_ACCOUNT와 저장소 이름을 실제 값으로 바꾼다.

```bash
python tools/validate.py
git init
git add README.md docs examples config tools .gitignore
git commit -m "docs: add XRMemory scene and decision graph design"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/XRMemory-SceneGraph.git
git push -u origin main
```

기존 팀 저장소에는 별도 브랜치로 추가한 뒤 Pull Request를 생성한다.
