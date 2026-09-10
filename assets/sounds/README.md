# 回弹音效来源

应用内默认使用“随机混合”，只在桌宠真正撞到屏幕边缘或地面时播放；拖动跟手的弹簧过程不播放声音。

- `bounce-retro-cc0.wav`：基于 [Retro video game sfx - Bounce](https://freesound.org/people/OwlStorm/sounds/404769/)，作者 OwlStorm，页面标注 CC0。
- `bounce-cute-cc0.wav`：基于 [Cute Bounce Jump.wav](https://freesound.org/people/Hemplock/sounds/618961/)，作者 Hemplock，页面标注 CC0。

两段音频都转换为单声道 24 kHz PCM WAV，只保留短音效，避免运行时引入音频解码库或加载长音频。
