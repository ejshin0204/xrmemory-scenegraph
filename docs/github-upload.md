# GitHub 업로드

ZIP을 풀고 README.md, docs, examples, config, tools가 있는 폴더를 저장소 루트로 사용합니다. ZIP 자체만 업로드하면 README가 첫 화면에 표시되지 않습니다.

GitHub에서 빈 저장소를 만든 뒤 아래 YOUR_ACCOUNT와 저장소 이름을 실제 값으로 바꿉니다.

```bash
python tools/validate.py
git init
git add README.md docs examples config tools .gitignore
git commit -m "docs: add XRMemory scene and decision graph design"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/XRMemory-SceneGraph.git
git push -u origin main
```

기존 팀 저장소에 추가할 경우 별도 브랜치에서 폴더를 추가하고 Pull Request로 검토합니다. 다른 저장소의 루트 파일을 덮어쓰지 않습니다. 라이선스는 팀의 공개·배포 정책을 정한 뒤 추가합니다.
