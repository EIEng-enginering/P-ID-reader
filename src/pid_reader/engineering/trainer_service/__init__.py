"""Background training service for the learned symbol detector (TR1).

A detached, low-priority runner process supervises the guarded trainer in tools/tr1_train. The Reader (GUI or CLI) only starts it and reads/writes small
state files, so it never blocks, and a run survives closing the Reader. Candidate models only: nothing here changes the active detector, the project
database or any engineering data.
"""
