

# Rufus-Py

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Discord](https://img.shields.io/discord/1477694881127469202?style=flat\&logo=https%3A%2F%2Fcdn.discordapp.com%2Ficons%2F1477694881127469202%2F1b2c4e8defc9220de11098108fa1ed81.webp%3Fsize%3D256\&logoColor=rgb\&label=Join%20Server\&link=https%3A%2F%2Fdiscord.gg%2FTMnXwezsyV)
![Status: Beta](https://img.shields.io/badge/status-beta-orange)

## 🚧 Beta Release

**Rufus-Py** is currently in **Beta**.

Rufus-Py is a physical drive imaging and formatting utility written in Python, inspired by Rufus. The goal is to provide a modern, Linux-native alternative with a clean interface and an intuitive workflow.

The project is under active development. Core functionality is being implemented and refined, and architectural decisions are still evolving.

⚠️ **Important Notice**

* Expect bugs
* Expect incomplete features
* Expect breaking changes between versions
* Not recommended for mission-critical production environments

If you require a fully stable imaging solution, consider established tools until Rufus-Py reaches a stable release.

---

## ✨ Current Features (Beta)

* ISO image selection
* Physical drive detection
* Basic image writing workflow
* Simple, minimal UI
* Preliminary error handling

> Feature set will expand as development continues.

---

## 🛠 Planned Features

* Advanced partition scheme selection (MBR / GPT)
* Filesystem selection (FAT32, NTFS, exFAT)
* Persistent storage configuration (for supported ISOs)
* Image verification after write
* Better device safety validation
* Multi-language support
* Improved logging and debug mode
* Plugin architecture for extended functionality

---

## 🎯 Project Vision

Rufus-Py aims to:

* Bring familiar USB imaging workflows to Linux
* Simplify bootable media creation for newer Linux users
* Provide a clean, minimal, and accessible interface
* Maintain transparency in how drives are written
* Build a lightweight, Python-based foundation for long-term extensibility

Unlike platform-locked tools, Rufus-Py is designed with Linux-first principles in mind while remaining approachable for users migrating from Windows environments.

---

## 🧱 Technical Goals

* Modular project structure
* Clear separation between UI and backend logic
* Safe physical device interaction
* Clean, readable Python codebase
* Well-documented internal APIs
* Future CLI mode support

---

## 📦 Installation (Experimental)

```bash
git clone https://github.com/yourusername/rufus-py.git
cd rufus-py
pip install -r requirements.txt
python main.py
```

> Installation steps may change as packaging improves.

---

## 🧪 Testing & Stability

Because Rufus-Py interacts directly with physical drives:

* Always test with removable media.
* Do not test on production systems.
* Double-check selected drives before writing.

You are responsible for data loss caused by improper use.

---

## 🤝 Contributing

Feedback, testing, and contributions are appreciated.

This is an open-source project maintained by volunteers and hobbyists. Response times for issues and pull requests may vary.

Ways to contribute:

* Report bugs
* Suggest features
* Improve documentation
* Refactor modules
* Submit pull requests

Before submitting large changes, consider opening an issue for discussion.

---

## 📜 License

This project is licensed under the MIT License.
See the `LICENSE` file for details.


