'''
Created on Apr 15, 2010

@author: ivan
'''
import sys
import mad 
import os.path
import wave
import struct
import mymfcc
try:
    import ao
except:
    print >>sys.stderr, "WARNING: pyao module missing, will not be able to play audio"
    

import numpy
import logging, types

logger=logging.getLogger()

class AbortedByUser(Exception):
    pass
def analyze_segments(mp3_files, dir='', progress_callback=None, step_sec=0.3, limit=500, 
                     silence_sec=0.03, start_index=None, end_index=None):
    seg_length=[]
    seg_no=[]
    for i,mp3_file in enumerate(mp3_files):  
        f=os.path.join(dir, mp3_file)
        a, sr= load_audio_sample(f)
        segments=segment_audio(a, sr, step_sec, limit, silence_sec )
        seg_no.append(len(segments))
        seg_length.extend([float(len(s))/float(sr) for s in segments[start_index: end_index]])
        if progress_callback:
            try:
                progress_callback(i)
            except AbortedByUser:
                return ''
    seg_length=numpy.array(seg_length, dtype=numpy.float)
    seg_no=numpy.array(seg_no, dtype=numpy.int)
    
    return "Segments number per sample: min=%d, max=%d, mean=%.4f std=%.4f var=%.4f\n" % \
        (seg_no.min(), seg_no.max(), seg_no.mean(), seg_no.std(), seg_no.var()) + \
        "Segments lengths(sec): min=%.4f, max=%.4f, mean=%.4f std=%.4f var=%.4f\n" % \
        (seg_length.min(), seg_length.max(), seg_length.mean(), seg_length.std(), seg_length.var())

def signal_envelope(data_array):
    return numpy.abs(data_array)  

def calc_energy_env(a, sr, win_size=0.01):
    wsize=win_size*sr
    a=numpy.array(a, dtype=numpy.int32)
    win= numpy.ones(wsize, dtype=numpy.float) / float(wsize) / 10737418.24 
    e= numpy.convolve(a * a, win, 'same')
    return e
    

def segment_audio(data_array, sr, step_sec=0.35, limit =500, 
                  silence_sec=0.03, size_sec=None, seg_details=None, sound_canvas=0.5):
    step=int(round(step_sec*sr))
    silence=silence_sec*sr
    if sound_canvas:
        sound_canvas=int(round(silence*sound_canvas))
    env=calc_energy_env(data_array,sr)  
    i=0 
    in_segment=False
    seg_start=0
    segments=[]
    silence_detected=0
    while i<len(env) :
        if env[i]>limit:
            silence_detected=0
        if env[i]<=limit and in_segment:
            silence_detected+=1
            if silence_detected>=silence:
                in_segment=False
                segments.append([seg_start, i-silence])
                
        elif env[i]>limit and not in_segment:
            in_segment=True
            seg_start=i
            i+=step
        i+=1
    if in_segment:
        segments.append([seg_start, len(env)-1])
    segments=numpy.array(segments, dtype=numpy.int)
    if seg_details is not None and hasattr(seg_details, 'extend'):
        seg_details.extend(segments)
    dbg_segments(segments, sr)
    return cut_segments(data_array, sr, segments, None, sound_canvas)
    
    
def segment_audio_oldest(data_array, sr, step_sec=0.01, limit=0.05, size_sec=None):
    
    step=int(step_sec*sr)
    steps=numpy.ceil(float(len(data_array))/step)
    a=numpy.resize(data_array,(steps,step))
    p=numpy.square(a.astype(numpy.float)/32767).mean(1)
    started=False
    low_segments=0
    high_segments=0
    start_index=0
    stop_index=0
    segments=[]
    for i,val in enumerate(p):
        if val>limit:
            if started:
                low_segments=0
            else:
                if not high_segments:
                    start_index=i
                high_segments+=1
                if high_segments>=3:
                    started=True
                    high_segments=0
        else:
            if started:
                if not low_segments:
                    stop_index=i
                low_segments+=1
                if low_segments>=10:
                    started=False
                    low_segments=0
                    segments.append([start_index, stop_index])
                    
            else:
                high_segments=0
    if started:
        segments.append([start_index, i+1])
        
    segments=numpy.array(segments, dtype=numpy.int)*step
    
    
    dbg_segments(segments, sr)
    return cut_segments(a, sr, segments, size_sec)
    
def dbg_segments(segments, sr):    
    if logger.level and logger.level>logging.DEBUG:
        return
    sr=float(sr)
    diff=(segments[:, 1] - segments[:,0]) / sr
    logger.debug('Found %d segments: %s (lenghts %s)' % (len(segments), str(segments/sr), str(diff) ))
    
def cut_segments(a, sr, segments, size_sec=None, sound_canvas=None):
    
    ary_segments=[]
    if sound_canvas: 
        for i in xrange(len(segments)):
            s=segments[i][0]-sound_canvas
            if s < 0:
                s=0
            e=segments[i][1]+sound_canvas
            if e >= len(a):
                e=len(a)-1
                
            segments[i]=[s,e]
                  
    for s,e in segments:
        if size_sec:
            l=e-s
            nl=int(size_sec*sr)
            seg=numpy.resize(a.flat[s:e].copy(), int(size_sec*sr))
            # In contrary to documentation, if array is expanded, its not extended with zero, but with copy of itself
            if nl>l:
                seg[l:]=0
            ary_segments.append(seg)
        else:
            ary_segments.append(a.flat[s:e])
        
    return ary_segments



def play_array(a, sr):
    data=a.tostring()
    dev = ao.AudioDevice(0, bits=16, channels=1, rate=sr )
    #print dev.driver_info()
    dev.play(data)
    
def load_audio_sample(fname, ext=None):
    if not ext and isinstance(fname, types.StringTypes):
        ext = os.path.splitext(fname)[1].lower()
    if not ext:
        raise ValueError('Cannot determine audio type')
    if ext=='.mp3':
        return load_mp3_sample(fname)
    elif ext=='.wav':
        return load_wav_sample(fname)
    else:
        raise ValueError('Unknown audio type')
    
def load_wav_sample(fname):
    f=wave.open(fname)
    try:
        if f.getcomptype() != 'NONE':
            raise ValueError('Compressed WAVE format is not supported!')
        sr=f.getframerate()
        slen=f.getsampwidth()
        flen=f.getnframes()
        nchan= f.getnchannels()
        name=fname if isinstance(fname, types.StringTypes) else '<stream>'  
        logger.debug('Loading wav file %s: rate: %d, channels: %s, sample size: %s', name, sr, nchan, slen)
        if nchan <1 or nchan>2:
            raise ValueError('Only 1 or 2 channels are supported')
        if slen==1:
            sample_to_int=lambda i: (ord(i) - 128) * 256 # 1 byte PCM is unsigned, scaling up to 2 byte int
        elif slen==2:
            sample_to_int = lambda i : struct.unpack('<h',i)[0]
        else:
            raise ValueError('Only 1 or2 bytes sample size is supported')
        count=flen/nchan
        sample=[]
        for pos in xrange(count):
            if nchan==1:
                s=f.readframes(1)
                if not s:
                    raise ValueError('File %s ends early, at pos. %d'%(fname,pos))
                sample.append(sample_to_int(s))
            elif nchan==2:
                l=f.readframes(1)
                r=f.readframes(1)
                if not l or not r:
                    raise ValueError('Files ends early, at pos. %d'%pos)
                val = (sample_to_int(l)+sample_to_int(r))/2
                sample.append(val)
        return numpy.array(sample, dtype=numpy.int16), sr
    finally:
        f.close()
        
def load_mp3_sample(fname):
    mf=mad.MadFile(fname)
    name=fname if isinstance(fname, types.StringTypes) else '<stream>'  
    logger.debug('loading mp3 file %s : rate %d, layer %d, mode %d, total time %d' %
                 (name, mf.samplerate(), mf.layer(), mf.mode(), mf.total_time()))
    
    a=numpy.array([], dtype=numpy.int16)
    #TODO: this is not very effective
    while 1:
        #read frame
        audio=mf.read()
        if audio is None:
            break
        a=numpy.append(a,numpy.frombuffer(audio, dtype=numpy.int16))
        
    
    #a=numpy.fromstring(str(sample)[3:], dtype=numpy.int16)
    logger.debug('Lodaded %d words' % len(a))
    if mf.mode() in (3,2):
        a.shape=-1,2
        a=numpy.mean(a,1)
        a=numpy.around(a, out=numpy.zeros(a.shape, numpy.int16 ))
        
    return a, mf.samplerate()

def calc_mfcc(sample, sr, nbins):
    nwin=int(0.025*sr)
    nstep=int(0.01*sr)
    rs= mymfcc.mfcc(sample, sr, nbins)
    numpy.ma.fix_invalid(rs, copy=False, fill_value=0)
    logger.debug("Calculated MFCC size: %s " % str(rs.shape))
    return rs
