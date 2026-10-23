# -*- coding: utf-8 -*-
"""uvprojx: Drivers 组加 HAL TIM 驱动两个文件."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(ROOT, 'MDK-ARM', 'ctrl_2005.uvprojx')
t = open(p, 'rb').read().decode('utf-8')

old = ('              <FileName>stm32f4xx_hal_exti.c</FileName>\n'
       '              <FileType>1</FileType>\n'
       '              <FilePath>../Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_exti.c</FilePath>\n'
       '            </File>')
new = old + ('\n'
       '            <File>\n'
       '              <FileName>stm32f4xx_hal_tim.c</FileName>\n'
       '              <FileType>1</FileType>\n'
       '              <FilePath>../Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_tim.c</FilePath>\n'
       '            </File>\n'
       '            <File>\n'
       '              <FileName>stm32f4xx_hal_tim_ex.c</FileName>\n'
       '              <FileType>1</FileType>\n'
       '              <FilePath>../Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_tim_ex.c</FilePath>\n'
       '            </File>')
n = t.count(old)
assert n == 1, 'exti anchor hit %d' % n
t = t.replace(old, new, 1)
open(p, 'wb').write(t.encode('utf-8'))
print('uvprojx HAL TIM files added')
