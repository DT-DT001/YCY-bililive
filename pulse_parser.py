import math

FREQ_DATASET = [
    10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000,
]

DURATION_DATASET = [1, 2, 3, 4, 5, 8, 10, 15, 20, 30, 40, 50, 60]

def freq_from_index(index):
    clamped = max(0, min(len(FREQ_DATASET) - 1, int(math.floor(index))))
    return FREQ_DATASET[clamped]

def duration_from_index(index):
    clamped = max(0, min(len(DURATION_DATASET) - 1, int(math.floor(index))))
    return DURATION_DATASET[clamped]

def encode_freq(value):
    # 将原始频率映射到 1-100 的范围内，符合协议限制
    output = round(value)
    return max(1, min(100, output))

def parse_pulse_text(data: str):
    trimmed = data.strip()
    if not trimmed.lower().startswith("dungeonlab+pulse:"):
        raise ValueError("脉冲格式无效，必须以 'Dungeonlab+pulse:' 开头")
        
    clean_data = trimmed[17:]
    section_parts = clean_data.split("+section+")
    if not section_parts or not section_parts[0]:
        raise ValueError("脉冲数据无效，未找到任何分段")
        
    first_part = section_parts[0]
    equal_index = first_part.find('=')
    if equal_index == -1:
        raise ValueError("脉冲格式无效，缺少 '=' 分隔符")
        
    embedded_name = first_part[:equal_index].strip()
    sections = []
    
    first_section_data = first_part[equal_index + 1:]
    all_section_data = [first_section_data] + section_parts[1:]
    
    for i in range(min(len(all_section_data), 10)):
        section_data = all_section_data[i]
        if not section_data:
            continue
        slash_index = section_data.find('/')
        if slash_index == -1:
            raise ValueError(f"第 {i + 1} 段缺少 '/' 分隔符")
            
        header_part = section_data[:slash_index]
        shape_part = section_data[slash_index + 1:]
        
        header_values = header_part.split(',')
        freq_range1_index = float(header_values[0]) if len(header_values) > 0 and header_values[0] else 0
        freq_range2_index = float(header_values[1]) if len(header_values) > 1 and header_values[1] else 0
        duration_index = float(header_values[2]) if len(header_values) > 2 and header_values[2] else 0
        freq_mode = float(header_values[3]) if len(header_values) > 3 and header_values[3] else 1
        enabled = (header_values[4] != '0') if len(header_values) > 4 else True
        
        shape_points = []
        for item in shape_part.split(','):
            if not item:
                continue
            parts = item.split('-')
            strength_str = parts[0]
            try:
                strength = round(float(strength_str))
            except ValueError:
                strength = 0
            shape_points.append({"strength": max(0, min(100, strength))})
            
        if len(shape_points) < 2:
            raise ValueError(f"第 {i + 1} 段至少需要 2 个形状点")
            
        if enabled:
            sections.append({
                "frequencyMode": freq_mode,
                "shape": shape_points,
                "startFrequency": freq_from_index(freq_range1_index),
                "endFrequency": freq_from_index(freq_range2_index),
                "duration": duration_from_index(duration_index)
            })
            
    if not sections:
        raise ValueError("脉冲数据无效，没有启用的分段")
        
    frames = []
    for section in sections:
        shape_count = len(section["shape"])
        pulse_element_duration = shape_count
        section_duration = section["duration"]
        
        start_frequency = section["startFrequency"]
        end_frequency = section["endFrequency"]
        frequency_mode = section["frequencyMode"]
        
        pulse_element_count = max(1, math.ceil(section_duration / pulse_element_duration))
        actual_duration = pulse_element_count * pulse_element_duration
        
        for element_index in range(pulse_element_count):
            for shape_index in range(shape_count):
                strength = section["shape"][shape_index].get("strength", 0)
                current_time = element_index * pulse_element_duration + shape_index
                section_progress = current_time / actual_duration
                element_progress = shape_index / shape_count
                
                if frequency_mode == 2:
                    raw_freq = start_frequency + (end_frequency - start_frequency) * section_progress
                elif frequency_mode == 3:
                    raw_freq = start_frequency + (end_frequency - start_frequency) * element_progress
                elif frequency_mode == 4:
                    progress = (element_index / (pulse_element_count - 1)) if pulse_element_count > 1 else 0
                    raw_freq = start_frequency + (end_frequency - start_frequency) * progress
                else:
                    raw_freq = start_frequency
                    
                frames.append({
                    "freq": encode_freq(raw_freq),
                    "intensity_scale": max(0, min(100, round(strength))) / 100.0,
                    "pulse": 50
                })
                
    if not frames:
        raise ValueError("解析后的波形为空")
        
    return {"name": embedded_name, "data": frames}
