"""Disjoint legal movement profiles for training, validation and confirmation."""
TRAIN=[(direction,walk,wait) for direction in (1,2) for walk in (0,2,4,6) for wait in (0,2)]
VALIDATION=[(direction,walk,1) for direction in (1,2) for walk in (1,3,5)]
CONFIRMATION=[(direction,walk,3) for direction in (1,2) for walk in (3,5,7)]

def profile(bank,index):
    choices={'train':TRAIN,'validation':VALIDATION,'confirmation':CONFIRMATION}[bank]
    return choices[index%len(choices)]
