"""내보내기·불러오기: OBJ(+그룹) / 프로젝트 단위 변환(케라투라: ×0.598, y-up·z 앞)."""
import numpy as np

H_BLENDER = 0.598


def to_project(V, F, project):
    """하네스 좌표(X 오른쪽, Y 앞, Z 위, 단위 H) → 프로젝트 좌표. 축을 바꾸면 손잡이가 뒤집혀 면 순서도 뒤집는다."""
    if project is None:
        return V, F
    if project != 'keratoura':
        raise ValueError('알 수 없는 프로젝트 ' + project)
    W = np.stack([V[:, 0], V[:, 2], V[:, 1]], 1) * H_BLENDER       # x, y(위), z(앞)
    return W, F[:, ::-1]


def write_obj(path, V, F, project=None, groups=None, header=''):
    """groups: {이름: 삼각형 번호 배열}. 없으면 전체를 'head' 그룹으로."""
    W, G = to_project(np.asarray(V, float), np.asarray(F, int), project)
    if project is not None and groups is not None:
        pass                                                      # 면 번호는 그대로(순서만 뒤집음)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('# ModelerHarness v0.1 %s\n' % header)
        f.write('# 정점 %d 삼각형 %d%s\n' % (len(W), len(G), ' 단위=' + project if project else ' 단위=H'))
        for p in W:
            f.write('v %.6f %.6f %.6f\n' % tuple(p))
        if groups is None:
            groups = {'head': np.arange(len(G))}
        for name, ids in groups.items():
            f.write('g %s\n' % name)
            for t in ids:
                a, b, c = G[t] + 1
                f.write('f %d %d %d\n' % (a, b, c))


def read_obj(path):
    V, F = [], []
    for line in open(path, encoding='utf-8'):
        if line.startswith('v '):
            p = line.split()
            V.append((float(p[1]), float(p[2]), float(p[3])))
        elif line.startswith('f '):
            idx = [int(t.split('/')[0]) for t in line.split()[1:]]
            idx = [i - 1 if i > 0 else len(V) + i for i in idx]
            for k in range(1, len(idx) - 1):
                F.append((idx[0], idx[k], idx[k + 1]))
    return np.array(V, float).reshape(-1, 3), np.array(F, int).reshape(-1, 3)
