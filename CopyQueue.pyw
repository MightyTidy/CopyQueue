import keyboard
import win32clipboard
import time

CopyQueue = []
Qcount = 0
placeCount = 0
QueueMode = True


def fToggleQueueMode():
    global QueueMode
    if QueueMode:
        QueueMode = False
    else:
        QueueMode = True
    return QueueMode


def fAddCounter():
    global Qcount
    Qcount = Qcount + 1
    return Qcount


def fPlaceCountAddCounter():
    global placeCount
    placeCount = placeCount + 1
    return placeCount


def fPlaceCountSubtractCounter():
    global placeCount
    placeCount = placeCount - 1
    return placeCount


def fSubtractCounter():
    global Qcount
    Qcount = Qcount - 1
    return Qcount


def fEnqueueCopyQueue():
    print("\nin Enqueue Func\n")
    if QueueMode:
        time.sleep(0.10)
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData()
        win32clipboard.CloseClipboard()
        CopyQueue.append(data)
        fAddCounter()
        print("\nCopyQueue[n] is", CopyQueue[len(CopyQueue) - 1], "\nand QCount = ", Qcount)


def fDequeueCopyQueue():
    if QueueMode:
        if Qcount > 0:
            print("\nin dequeue Func\n CopyQueue[0] = ", CopyQueue[0])
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(CopyQueue[0])
            win32clipboard.CloseClipboard()
            CopyQueue.pop(0)
            fSubtractCounter()
            if not CopyQueue:
                print("Queue is empty", Qcount)
            else:
                print("\nDequeue = CopyQueue[n] is", CopyQueue[len(CopyQueue) - 1], "\nand QCount = ", Qcount)


def fPauseProg():
    print('started pauseProg')
    fToggleQueueMode()
    time.sleep(1)


def fNextInQueue():
    print('started nextinqueue')
    if Qcount > 0 and placeCount < len(CopyQueue)-1:
        print("Qcount = ", Qcount, "placeCount = ",placeCount)
        fPlaceCountAddCounter()
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(CopyQueue[placeCount])
        win32clipboard.CloseClipboard()
        time.sleep(0.1)


def fPrevInQueue():
    print('started previnqueue')
    if Qcount > 0 and placeCount > 0:
        fPlaceCountSubtractCounter()
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(CopyQueue[placeCount])
        win32clipboard.CloseClipboard()
        time.sleep(0.1)


def initProgram():
    keyboard.add_hotkey('ctrl+c', fEnqueueCopyQueue)
    keyboard.add_hotkey('ctrl+v', fDequeueCopyQueue)
    keyboard.add_hotkey('ctrl+b', fPauseProg)
    keyboard.add_hotkey('ctrl+right', fNextInQueue)
    keyboard.add_hotkey('ctrl+left', fPrevInQueue)
    keyboard.wait('ctrl+esc')


initProgram()
